"""Provider-agnostic LLM client seam.

A single async ``complete`` method is all the services need; each provider's
differences (system-prompt placement, structured-output support) are confined
to its own thin adapter. Errors are translated into ``LLMError`` so callers can
decide whether a failure is worth retrying without knowing which SDK raised it.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Protocol, runtime_checkable

from app.core.config import settings

logger = logging.getLogger(__name__)

# Backoff shape shared by complete_with_retry. Matches the per-service retry
# loops this seam replaces (1s, 2s, ... with ±0.5s jitter).
_RETRY_BASE_DELAY = 1.0  # seconds
_RETRY_BACKOFF_FACTOR = 2.0
_RETRY_JITTER = 0.5  # ± seconds


class LLMError(Exception):
    """The single exception raised by every LLM adapter.

    ``status_code`` is the provider's HTTP status when one exists. It is
    ``None`` for connection errors and timeouts, which are always transient.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    @property
    def is_transient(self) -> bool:
        """Whether retrying the call could plausibly succeed.

        Status-based, not exception-type-based: a 401 or 404 must fail fast
        instead of burning the retry budget on an error that cannot recover.
        """
        if self.status_code is None:
            return True
        return self.status_code == 429 or self.status_code >= 500


@runtime_checkable
class LLMClient(Protocol):
    """Structural interface implemented by every provider adapter."""

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        max_tokens: int,
        system_prompt: str | None = None,
        timeout: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Return the assistant's text for ``messages``."""
        ...


_anthropic_key_warned = False


def _resolve_anthropic_api_key() -> str:
    """``LLM_API_KEY``, else legacy ``ANTHROPIC_API_KEY`` (warn once), else ""."""
    global _anthropic_key_warned

    if settings.LLM_API_KEY:
        return settings.LLM_API_KEY
    if settings.ANTHROPIC_API_KEY:
        if not _anthropic_key_warned:
            logger.warning(
                "LLM_API_KEY is not set; falling back to ANTHROPIC_API_KEY. "
                "Set LLM_API_KEY to use a different Anthropic credential."
            )
            _anthropic_key_warned = True
        return settings.ANTHROPIC_API_KEY
    return ""


class AnthropicAdapter:
    """Native Anthropic backend (``/v1/messages``)."""

    def __init__(
        self,
        *,
        base_url: str = "",
        api_key: str | None = None,
    ) -> None:
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        key = _resolve_anthropic_api_key() if api_key is None else api_key
        client_kwargs: dict[str, Any] = {"api_key": key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**client_kwargs)
        self._semaphore = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        max_tokens: int,
        system_prompt: str | None = None,
        timeout: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Send a completion request, ignoring ``response_format``.

        Anthropic's API has no ``response_format`` parameter; structured output
        relies on prompt instructions plus application-side schema validation.
        """
        import anthropic  # noqa: PLC0415

        kwargs: dict[str, Any] = {
            "model": model.removeprefix("anthropic/"),
            "max_tokens": max_tokens,
            "messages": messages,
            "timeout": settings.LLM_TIMEOUT if timeout is None else timeout,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        try:
            async with self._semaphore:
                response = await self._client.messages.create(**kwargs)
        except anthropic.APIStatusError as exc:
            raise LLMError(str(exc), status_code=exc.status_code) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Anthropic connection error: {exc}") from exc
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise LLMError(f"Anthropic request timed out: {exc}") from exc

        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text
        raise LLMError("Anthropic response contained no text content block")


async def complete_with_retry(client: LLMClient, **kwargs: Any) -> str:
    """Call ``client.complete`` with exponential backoff on transient errors.

    Non-transient ``LLMError``s (bad key, bad model, malformed request) are
    raised on the first attempt. The last error is re-raised once the
    ``settings.LLM_MAX_RETRIES`` budget is exhausted.
    """
    max_attempts = max(1, settings.LLM_MAX_RETRIES)
    last_exc: LLMError | None = None

    for attempt in range(max_attempts):
        try:
            return await client.complete(**kwargs)
        except LLMError as exc:
            if not exc.is_transient or attempt == max_attempts - 1:
                raise
            last_exc = exc

        delay = _RETRY_BASE_DELAY * (_RETRY_BACKOFF_FACTOR ** attempt)
        sleep_time = max(0.0, delay + random.uniform(-_RETRY_JITTER, _RETRY_JITTER))
        logger.warning(
            "complete_with_retry: transient error on attempt %d/%d, "
            "retrying in %.2fs: %s",
            attempt + 1, max_attempts, sleep_time, last_exc,
        )
        await asyncio.sleep(sleep_time)

    raise last_exc  # type: ignore[misc]
