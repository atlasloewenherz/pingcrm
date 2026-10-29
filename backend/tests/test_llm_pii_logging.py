"""Transport-layer PII discipline for LLM logging.

The SDKs are capable of logging full request payloads (system prompts, contact
message bodies). These tests assert the two defenses in ``setup_logging()``:
SDK loggers are pinned at WARNING, and every handler carries a
``RedactMessagesFilter`` that scrubs message content before formatting.
"""
from __future__ import annotations

import io
import logging
import sys

from app.core.logging_config import RedactMessagesFilter, setup_logging

_SECRET = "my ex-wife's new address is 742 Evergreen Terrace"


def test_setup_logging_attaches_redact_filter_to_every_handler(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    setup_logging()

    assert logging.root.handlers
    for handler in logging.root.handlers:
        assert any(isinstance(f, RedactMessagesFilter) for f in handler.filters)


def test_sdk_loggers_are_pinned_at_warning(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    setup_logging()

    assert logging.getLogger("anthropic").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("openai").getEffectiveLevel() == logging.WARNING


def test_child_logger_does_not_leak_message_content(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    setup_logging()

    logger = logging.getLogger("app.services.llm").getChild("transport_test")
    logger.info(
        "LLM request payload: %s",
        {
            "model": "anthropic/claude-sonnet-4-6",
            "system": _SECRET,
            "messages": [{"role": "user", "content": _SECRET}],
        },
    )
    for handler in logging.root.handlers:
        handler.flush()

    output = stream.getvalue()
    assert output, "expected the console handler to emit the record"
    assert _SECRET not in output
    assert "[REDACTED]" in output
    # Non-sensitive context survives, so logs remain useful for debugging.
    assert "anthropic/claude-sonnet-4-6" in output


def test_filter_redacts_list_of_message_dicts_without_mutating_input():
    record = logging.LogRecord(
        name="app.services.llm",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="payload: %s",
        args=([{"role": "user", "content": _SECRET}],),
        exc_info=None,
    )
    original = record.args

    assert RedactMessagesFilter().filter(record) is True

    assert record.args is not original
    assert _SECRET not in repr(record.args)
    assert "[REDACTED]" in repr(record.args)
