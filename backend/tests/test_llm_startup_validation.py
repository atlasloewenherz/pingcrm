"""Startup validation runs in both the API and Celery worker runtimes."""
import pytest

from app.core.celery_app import _validate_llm_config_on_worker_start
from app.core.config import settings
from app.services.llm import SUPPORTED_PREFIXES, validate_llm_config


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-sonnet-4-6",
        "openai/gpt-4o",
        "ollama/llama3",
        "vllm/mistral",
    ],
)
def test_validate_llm_config_accepts_supported_prefixes(monkeypatch, model):
    monkeypatch.setattr(settings, "LLM_MODEL_DRAFT", model)
    monkeypatch.setattr(settings, "LLM_MODEL_FAST", model)

    validate_llm_config()


@pytest.mark.parametrize(
    "model",
    ["claude-sonnet-4-6", "gpt-4o", "unknown/model", ""],
)
def test_validate_llm_config_rejects_unsupported_draft_prefix(monkeypatch, model):
    monkeypatch.setattr(settings, "LLM_MODEL_DRAFT", model)
    monkeypatch.setattr(settings, "LLM_MODEL_FAST", "anthropic/claude-haiku-4-5-20251001")

    with pytest.raises(RuntimeError, match="LLM_MODEL_DRAFT"):
        validate_llm_config()


def test_validate_llm_config_rejects_unsupported_fast_prefix(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL_DRAFT", "anthropic/claude-sonnet-4-6")
    monkeypatch.setattr(settings, "LLM_MODEL_FAST", "bare-model-without-prefix")

    with pytest.raises(RuntimeError, match="LLM_MODEL_FAST"):
        validate_llm_config()


def test_error_lists_supported_prefixes(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL_DRAFT", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "LLM_MODEL_FAST", "anthropic/claude-haiku-4-5-20251001")

    with pytest.raises(RuntimeError) as excinfo:
        validate_llm_config()

    message = str(excinfo.value)
    for prefix in SUPPORTED_PREFIXES:
        assert prefix in message


def test_worker_signal_handler_raises_for_unprefixed_model(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL_DRAFT", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "LLM_MODEL_FAST", "anthropic/claude-haiku-4-5-20251001")

    with pytest.raises(RuntimeError, match="LLM_MODEL_DRAFT"):
        _validate_llm_config_on_worker_start()


def test_worker_signal_handler_passes_for_supported_models(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL_DRAFT", "openai/gpt-4o")
    monkeypatch.setattr(settings, "LLM_MODEL_FAST", "ollama/llama3")

    assert _validate_llm_config_on_worker_start() is None
