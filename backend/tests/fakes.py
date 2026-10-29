"""Test doubles for the LLM client seam."""
from __future__ import annotations

from typing import Any


class FakeLLMClient:
    """An ``LLMClient`` that records calls and returns canned responses.

    ``responses`` may mix strings and exceptions; each call consumes the next
    entry, which makes retry behavior testable without patching an SDK. Once
    the list is exhausted the last entry is reused.
    """

    def __init__(
        self,
        response: str = "",
        responses: list[str | Exception] | None = None,
    ) -> None:
        self.response = response
        self.responses = list(responses) if responses is not None else None
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        if self.responses:
            value = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
            if isinstance(value, Exception):
                raise value
            return value
        return self.response

    @property
    def last_call(self) -> dict[str, Any] | None:
        return self.calls[-1] if self.calls else None
