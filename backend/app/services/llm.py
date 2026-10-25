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
