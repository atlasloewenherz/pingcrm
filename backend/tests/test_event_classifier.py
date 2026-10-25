"""Tests for event classifier service."""
import pytest

from app.core.config import settings
from app.services.event_classifier import (
    _parse_classifier_response,
    classify_bio_change,
    classify_tweet,
)
from app.services.llm import LLMError


def test_parse_classifier_response_valid_json():
    raw = '{"event_type": "job_change", "confidence": 0.9, "summary": "New role at Google"}'
    result = _parse_classifier_response(raw)
    assert result["event_type"] == "job_change"
    assert result["confidence"] == 0.9
    assert result["summary"] == "New role at Google"


def test_parse_classifier_response_markdown_fenced():
    raw = '```json\n{"event_type": "fundraising", "confidence": 0.8, "summary": "Raised Series A"}\n```'
    result = _parse_classifier_response(raw)
    assert result["event_type"] == "fundraising"
    assert result["confidence"] == 0.8


def test_parse_classifier_response_invalid_json():
    raw = "this is not json"
    result = _parse_classifier_response(raw)
    assert result["event_type"] == "none"
    assert result["confidence"] == 0.0


def test_parse_classifier_response_invalid_event_type():
    raw = '{"event_type": "alien_invasion", "confidence": 0.5, "summary": "Aliens"}'
    result = _parse_classifier_response(raw)
    assert result["event_type"] == "none"


def test_parse_classifier_response_clamps_confidence():
    raw = '{"event_type": "job_change", "confidence": 1.5, "summary": "Test"}'
    result = _parse_classifier_response(raw)
    assert result["confidence"] == 1.0


@pytest.mark.asyncio
async def test_classify_tweet_uses_draft_model(fake_llm_client):
    fake_llm_client.response = (
        '{"event_type": "job_change", "confidence": 0.9, "summary": "Started new role"}'
    )

    result = await classify_tweet("Excited to announce I'm joining Google!", "testuser")

    assert result == {
        "event_type": "job_change",
        "confidence": 0.9,
        "summary": "Started new role",
    }
    call = fake_llm_client.last_call
    assert call is not None
    assert call["model"] == settings.LLM_MODEL_DRAFT
    assert call["max_tokens"] == 256
    assert call["system_prompt"]
    assert "joining Google" in call["messages"][0]["content"]


@pytest.mark.asyncio
async def test_classify_bio_change_uses_draft_model(fake_llm_client):
    fake_llm_client.response = (
        '{"event_type": "job_change", "confidence": 0.85, "summary": "Changed role"}'
    )

    result = await classify_bio_change(
        "Engineer at Startup", "CTO at BigCo", "testuser"
    )

    assert result["event_type"] == "job_change"
    assert result["confidence"] == 0.85
    call = fake_llm_client.last_call
    assert call is not None
    assert call["model"] == settings.LLM_MODEL_DRAFT
    assert "CTO at BigCo" in call["messages"][0]["content"]


@pytest.mark.asyncio
async def test_classify_tweet_llm_failure_returns_none(fake_llm_client):
    fake_llm_client.responses = [LLMError("authentication failed", status_code=401)]

    result = await classify_tweet("Hello world", "testuser")

    assert result == {"event_type": "none", "confidence": 0.0, "summary": ""}


@pytest.mark.asyncio
async def test_classify_bio_change_llm_failure_returns_none(fake_llm_client):
    fake_llm_client.responses = [LLMError("authentication failed", status_code=401)]

    result = await classify_bio_change("old", "new", "testuser")

    assert result == {"event_type": "none", "confidence": 0.0, "summary": ""}
