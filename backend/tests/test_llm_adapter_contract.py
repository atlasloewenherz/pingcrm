"""Contract tests for the two LLM adapters.

These tests pin the provider-specific translation rules (system-prompt
placement, structured-output handling) and the seam-level guarantees
(memoization, concurrency cap, error classification) without making any
network calls. The SDK clients are replaced at construction time with
recording fakes.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from app.core.config import settings
from app.services import llm
from app.services.llm import (
    AnthropicAdapter,
    LLMClient,
    LLMError,
    OpenAICompatibleAdapter,
    get_llm_client,
)


class RecordingAnthropicClient:
    """Stands in for ``anthropic.AsyncAnthropic``."""

    def __init__(self, response_text: str = "anthropic reply") -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)
        self._response_text = response_text

    async def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._response_text)]
        )


class RecordingOpenAIClient:
    """Stands in for ``openai.AsyncOpenAI``.

    ``errors`` is consumed per call; each entry is either a string (returned as
    the assistant message) or an exception to raise.
    """

    def __init__(self, errors: list[str | Exception] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(errors) if errors else ["openai reply"]
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    async def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        value = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=value))]
        )


def _install_anthropic(monkeypatch, client: RecordingAnthropicClient) -> list[dict]:
    """Make ``AnthropicAdapter`` construct ``client``; return constructor kwargs."""
    constructed: list[dict] = []

    def _factory(**kwargs: Any) -> RecordingAnthropicClient:
        constructed.append(kwargs)
        return client

    import anthropic

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _factory)
    return constructed


def _install_openai(monkeypatch, client: RecordingOpenAIClient) -> list[dict]:
    constructed: list[dict] = []

    def _factory(**kwargs: Any) -> RecordingOpenAIClient:
        constructed.append(kwargs)
        return client

    import openai as openai_sdk

    monkeypatch.setattr(openai_sdk, "AsyncOpenAI", _factory)
    return constructed


@pytest.fixture(autouse=True)
def _isolated_llm_state(monkeypatch):
    """Keep memoized clients and settings overrides from leaking across tests."""
    monkeypatch.setattr(llm, "_clients", {})
    monkeypatch.setattr(llm, "_clients_lock", asyncio.Lock())
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "")
    monkeypatch.setattr(settings, "LLM_ALLOW_EMPTY_KEY", False)
    monkeypatch.setattr(settings, "LLM_STRUCTURED_OUTPUT", "none")
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENCY", 5)


# ---------------------------------------------------------------------------
# System-prompt placement
# ---------------------------------------------------------------------------

async def test_anthropic_passes_system_as_top_level_kwarg(monkeypatch):
    client = RecordingAnthropicClient()
    _install_anthropic(monkeypatch, client)
    adapter = AnthropicAdapter(api_key="test-key")

    result = await adapter.complete(
        messages=[{"role": "user", "content": "hello"}],
        model="anthropic/claude-sonnet-4-6",
        max_tokens=64,
        system_prompt="You are terse.",
    )

    assert result == "anthropic reply"
    kwargs = client.calls[0]
    assert kwargs["system"] == "You are terse."
    assert kwargs["messages"] == [{"role": "user", "content": "hello"}]
    assert all(message.get("role") != "system" for message in kwargs["messages"])
    # The adapter strips the provider prefix before talking to the SDK.
    assert kwargs["model"] == "claude-sonnet-4-6"


async def test_openai_prepends_system_as_first_message(monkeypatch):
    client = RecordingOpenAIClient()
    _install_openai(monkeypatch, client)
    adapter = OpenAICompatibleAdapter(api_key="test-key")

    await adapter.complete(
        messages=[{"role": "user", "content": "hello"}],
        model="openai/gpt-4o",
        max_tokens=64,
        system_prompt="You are terse.",
    )

    kwargs = client.calls[0]
    assert kwargs["messages"][0] == {"role": "system", "content": "You are terse."}
    assert kwargs["messages"][1] == {"role": "user", "content": "hello"}
    assert kwargs["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------

async def test_anthropic_never_sends_response_format(monkeypatch):
    client = RecordingAnthropicClient()
    _install_anthropic(monkeypatch, client)
    adapter = AnthropicAdapter(api_key="test-key")

    await adapter.complete(
        messages=[{"role": "user", "content": "json please"}],
        model="anthropic/claude-sonnet-4-6",
        max_tokens=64,
        response_format={"type": "json_object"},
    )

    assert "response_format" not in client.calls[0]


async def test_openai_sends_response_format_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "LLM_STRUCTURED_OUTPUT", "json_object")
    client = RecordingOpenAIClient()
    _install_openai(monkeypatch, client)
    adapter = OpenAICompatibleAdapter(api_key="test-key")

    await adapter.complete(
        messages=[{"role": "user", "content": "json please"}],
        model="openai/gpt-4o",
        max_tokens=64,
        response_format={"type": "json_object"},
    )

    assert client.calls[0]["response_format"] == {"type": "json_object"}


async def test_openai_omits_response_format_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "LLM_STRUCTURED_OUTPUT", "none")
    client = RecordingOpenAIClient()
    _install_openai(monkeypatch, client)
    adapter = OpenAICompatibleAdapter(api_key="test-key")

    await adapter.complete(
        messages=[{"role": "user", "content": "json please"}],
        model="openai/gpt-4o",
        max_tokens=64,
        response_format={"type": "json_object"},
    )

    assert "response_format" not in client.calls[0]


async def test_structured_output_rejection_cache_skips_on_second_call(monkeypatch):
    monkeypatch.setattr(settings, "LLM_STRUCTURED_OUTPUT", "json_object")
    request = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")
    rejection = openai.APIStatusError(
        "response_format not supported",
        response=httpx.Response(400, request=request),
        body=None,
    )
    client = RecordingOpenAIClient(errors=[rejection, "first ok", "second ok"])
    _install_openai(monkeypatch, client)
    adapter = OpenAICompatibleAdapter(api_key="test-key")

    first = await adapter.complete(
        messages=[{"role": "user", "content": "json please"}],
        model="ollama/llama3",
        max_tokens=64,
        response_format={"type": "json_object"},
    )
    second = await adapter.complete(
        messages=[{"role": "user", "content": "json please"}],
        model="ollama/llama3",
        max_tokens=64,
        response_format={"type": "json_object"},
    )

    assert first == "first ok"
    assert second == "second ok"
    # First call: structured request rejected, then retried without it.
    assert "response_format" in client.calls[0]
    assert "response_format" not in client.calls[1]
    # Second call: rejection cached for this model, so response_format is
    # never attached at all.
    assert len(client.calls) == 3
    assert "response_format" not in client.calls[2]
    assert "llama3" in adapter._no_structured_output


async def test_openai_rejects_preexisting_system_message(monkeypatch):
    client = RecordingOpenAIClient()
    _install_openai(monkeypatch, client)
    adapter = OpenAICompatibleAdapter(api_key="test-key")

    with pytest.raises(ValueError, match="must not contain a system message"):
        await adapter.complete(
            messages=[
                {"role": "system", "content": "sneaky"},
                {"role": "user", "content": "hello"},
            ],
            model="openai/gpt-4o",
            max_tokens=64,
        )

    assert client.calls == []


# ---------------------------------------------------------------------------
# Empty-key handling
# ---------------------------------------------------------------------------

def test_empty_key_allowed_for_self_hosted_server(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOW_EMPTY_KEY", True)
    client = RecordingOpenAIClient()
    constructed = _install_openai(monkeypatch, client)

    adapter = OpenAICompatibleAdapter(
        base_url="http://localhost:11434/v1", api_key=""
    )

    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert constructed == [
        {"api_key": "not-needed", "base_url": "http://localhost:11434/v1"}
    ]


def test_empty_key_rejected_when_empty_keys_not_allowed(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOW_EMPTY_KEY", False)

    with pytest.raises(ValueError, match="LLM_ALLOW_EMPTY_KEY"):
        OpenAICompatibleAdapter(base_url="http://localhost:11434/v1", api_key="")


# ---------------------------------------------------------------------------
# Error classification and protocol conformance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [429, 500, 502, 503, 529])
def test_llm_error_transient_statuses(status):
    assert LLMError("boom", status_code=status).is_transient is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_llm_error_permanent_statuses(status):
    assert LLMError("boom", status_code=status).is_transient is False


def test_llm_error_without_status_is_transient():
    assert LLMError("connection reset").is_transient is True


def test_adapters_satisfy_llm_client_protocol(monkeypatch):
    _install_anthropic(monkeypatch, RecordingAnthropicClient())
    _install_openai(monkeypatch, RecordingOpenAIClient())

    assert isinstance(AnthropicAdapter(api_key="test-key"), LLMClient)
    assert isinstance(OpenAICompatibleAdapter(api_key="test-key"), LLMClient)


# ---------------------------------------------------------------------------
# Factory memoization
# ---------------------------------------------------------------------------

async def test_get_llm_client_memoizes_identical_config(monkeypatch):
    built: list[Any] = []

    def _factory(**kwargs: Any) -> RecordingOpenAIClient:
        client = RecordingOpenAIClient()
        built.append(client)
        return client

    import openai as openai_sdk

    monkeypatch.setattr(openai_sdk, "AsyncOpenAI", _factory)

    first = await get_llm_client("openai/gpt-4o")
    second = await get_llm_client("openai/gpt-4o-mini")

    assert first is second
    assert len(built) == 1


async def test_get_llm_client_rebuilds_when_base_url_changes(monkeypatch):
    built: list[Any] = []

    def _factory(**kwargs: Any) -> RecordingOpenAIClient:
        client = RecordingOpenAIClient()
        built.append(client)
        return client

    import openai as openai_sdk

    monkeypatch.setattr(openai_sdk, "AsyncOpenAI", _factory)

    first = await get_llm_client("openai/gpt-4o")

    monkeypatch.setattr(settings, "LLM_BASE_URL", "http://localhost:11434/v1")
    second = await get_llm_client("openai/gpt-4o")

    assert first is not second
    assert len(built) == 2


# ---------------------------------------------------------------------------
# Concurrency cap
# ---------------------------------------------------------------------------

async def test_concurrency_never_exceeds_configured_limit(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENCY", 5)
    in_flight = 0
    peak = 0

    class BlockingClient(RecordingOpenAIClient):
        async def _create(self, **kwargs: Any) -> Any:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            try:
                await asyncio.sleep(0.02)
            finally:
                in_flight -= 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    _install_openai(monkeypatch, BlockingClient())
    adapter = OpenAICompatibleAdapter(api_key="test-key")

    async def _call() -> str:
        return await adapter.complete(
            messages=[{"role": "user", "content": "hi"}],
            model="openai/gpt-4o",
            max_tokens=8,
        )

    results = await asyncio.gather(*(_call() for _ in range(6)))

    assert results == ["ok"] * 6
    assert peak <= 5
