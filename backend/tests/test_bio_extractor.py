"""Tests for the bio extractor's use of the LLM client seam."""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.bio_extractor import extract_from_bios
from app.services.llm import LLMError


@pytest.mark.asyncio
async def test_extracts_structured_fields_from_fenced_json(fake_llm_client):
    fake_llm_client.response = (
        "```json\n"
        '{"given_name": "Ada", "family_name": "Lovelace", "company": "Analytical Engines",'
        ' "company_location": "London", "unknown": "ignored"}\n'
        "```"
    )

    result = await extract_from_bios(
        full_name="Ada Lovelace",
        twitter_bio="Mathematician building analytical engines",
    )

    assert result == {
        "given_name": "Ada",
        "family_name": "Lovelace",
        "company": "Analytical Engines",
        "company_location": "London",
    }

    call = fake_llm_client.last_call
    assert call is not None
    assert call["model"] == settings.LLM_MODEL_FAST
    assert call["max_tokens"] == 300
    assert call["timeout"] == 30.0


@pytest.mark.asyncio
async def test_timeout_comes_from_settings(fake_llm_client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_TIMEOUT_BIO_EXTRACTOR", 123.0)
    fake_llm_client.response = "{}"

    await extract_from_bios(full_name="Ada Lovelace")

    assert fake_llm_client.last_call["timeout"] == 123.0


@pytest.mark.asyncio
async def test_no_source_text_returns_empty_without_calling_llm(fake_llm_client):
    result = await extract_from_bios()

    assert result == {}
    assert fake_llm_client.calls == []


@pytest.mark.asyncio
async def test_unparseable_response_returns_empty(fake_llm_client):
    fake_llm_client.response = "this is not json"

    result = await extract_from_bios(full_name="Ada Lovelace")

    assert result == {}


@pytest.mark.asyncio
async def test_non_object_response_returns_empty(fake_llm_client):
    fake_llm_client.response = '["Ada", "Lovelace"]'

    result = await extract_from_bios(full_name="Ada Lovelace")

    assert result == {}


@pytest.mark.asyncio
async def test_llm_error_propagates(fake_llm_client):
    fake_llm_client.responses = [LLMError("bad request", status_code=400)]

    with pytest.raises(LLMError):
        await extract_from_bios(full_name="Ada Lovelace")
