"""Tests for auto_tagger service."""
import pytest

from app.core.config import settings
from app.services.auto_tagger import (
    _build_contact_summary,
    _parse_json_response,
    assign_tags,
    discover_taxonomy,
    merge_tags,
)
from app.services.llm import LLMError
from tests.fakes import FakeLLMClient


# ---------------------------------------------------------------------------
# merge_tags
# ---------------------------------------------------------------------------

class TestMergeTags:
    def test_case_insensitive_dedup(self):
        result = merge_tags(["CEO", "Founder"], ["ceo", "Developer"])
        assert result == ["CEO", "Founder", "Developer"]

    def test_append_only_never_removes(self):
        existing = ["CEO", "Founder"]
        result = merge_tags(existing, [])
        assert "CEO" in result
        assert "Founder" in result
        assert len(result) == 2

    def test_none_existing(self):
        result = merge_tags(None, ["A"])
        assert result == ["A"]

    def test_empty_new_tags_returns_existing_unchanged(self):
        existing = ["Tag1", "Tag2"]
        result = merge_tags(existing, [])
        assert result == ["Tag1", "Tag2"]

    def test_preserves_order_existing_first(self):
        result = merge_tags(["B", "A"], ["C", "D"])
        assert result == ["B", "A", "C", "D"]

    def test_preserves_existing_case_on_duplicate(self):
        # "CEO" is existing; "ceo" is new — "CEO" canonical form is kept, not added again
        result = merge_tags(["CEO"], ["ceo", "Founder"])
        assert result.count("CEO") == 1
        assert "ceo" not in result
        assert "Founder" in result

    def test_empty_existing_list(self):
        result = merge_tags([], ["X", "Y"])
        assert result == ["X", "Y"]

    def test_all_new_already_present(self):
        result = merge_tags(["A", "B"], ["a", "B"])
        assert len(result) == 2

    def test_returns_new_list_not_mutation(self):
        existing = ["A"]
        result = merge_tags(existing, ["B"])
        assert result is not existing


# ---------------------------------------------------------------------------
# _build_contact_summary
# ---------------------------------------------------------------------------

class TestBuildContactSummary:
    def test_all_fields_populated(self):
        contact = {
            "full_name": "Jane Doe",
            "title": "CTO",
            "company": "Acme",
            "twitter_bio": "Building things",
            "telegram_bio": "Crypto builder",
            "notes": "Met at conference",
            "tags": ["Founder", "AI"],
            "location": "San Francisco",
            "interaction_topics": ["Web3", "AI Safety"],
        }
        summary = _build_contact_summary(contact)
        assert "Name:" in summary
        assert "Title:" in summary
        assert "Company:" in summary
        assert "Twitter bio:" in summary
        assert "Telegram bio:" in summary
        assert "Notes:" in summary
        assert "Existing tags:" in summary
        assert "Location:" in summary
        assert "Interaction topics:" in summary

    def test_empty_dict_returns_minimal_data(self):
        result = _build_contact_summary({})
        assert result == "(minimal data)"

    def test_values_wrapped_in_value_tags(self):
        contact = {"full_name": "Alice"}
        summary = _build_contact_summary(contact)
        assert "<value>Alice</value>" in summary

    def test_long_name_truncated_at_100_chars(self):
        long_name = "A" * 200
        contact = {"full_name": long_name}
        summary = _build_contact_summary(contact)
        # The truncated name inside <value> tags should be 100 chars
        assert "<value>" + "A" * 100 + "</value>" in summary
        assert "A" * 101 not in summary

    def test_long_twitter_bio_truncated_at_200_chars(self):
        long_bio = "B" * 300
        contact = {"twitter_bio": long_bio}
        summary = _build_contact_summary(contact)
        assert "<value>" + "B" * 200 + "</value>" in summary
        assert "B" * 201 not in summary

    def test_notes_filter_excludes_twitter_bio_sentinel(self):
        contact = {
            "notes": "Met at ETHdenver\n__twitter_bio__: Engineer at Acme\nFollowup needed",
        }
        summary = _build_contact_summary(contact)
        assert "__twitter_bio__:" not in summary
        assert "Met at ETHdenver" in summary
        assert "Followup needed" in summary

    def test_notes_only_sentinel_lines_gives_empty_notes(self):
        contact = {"notes": "__twitter_bio__: some bio"}
        summary = _build_contact_summary(contact)
        # After filtering, trimmed is empty → Notes line should not appear
        assert "Notes:" not in summary

    def test_tags_list_formatted_correctly(self):
        contact = {"tags": ["CEO", "Founder", "AI"]}
        summary = _build_contact_summary(contact)
        assert "Existing tags:" in summary
        assert "CEO" in summary
        assert "Founder" in summary
        assert "AI" in summary

    def test_missing_optional_fields_skipped(self):
        contact = {"full_name": "Bob"}
        summary = _build_contact_summary(contact)
        assert "Title:" not in summary
        assert "Company:" not in summary
        assert "Twitter bio:" not in summary


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def test_bare_json_object(self):
        result = _parse_json_response('{"a": 1}')
        assert result == {"a": 1}

    def test_code_fence_with_language(self):
        raw = '```json\n{"a": 1}\n```'
        result = _parse_json_response(raw)
        assert result == {"a": 1}

    def test_code_fence_without_language(self):
        raw = '```\n{"a": 1}\n```'
        result = _parse_json_response(raw)
        assert result == {"a": 1}

    def test_invalid_json_returns_none(self):
        result = _parse_json_response("this is not json at all")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _parse_json_response("")
        assert result is None

    def test_bare_json_array(self):
        result = _parse_json_response('["x", "y"]')
        assert result == ["x", "y"]

    def test_whitespace_stripped(self):
        result = _parse_json_response('  {"b": 2}  ')
        assert result == {"b": 2}

    def test_nested_object(self):
        raw = '{"Role": ["CEO", "Founder"], "Industry": ["Tech"]}'
        result = _parse_json_response(raw)
        assert result["Role"] == ["CEO", "Founder"]
        assert result["Industry"] == ["Tech"]


# ---------------------------------------------------------------------------
# discover_taxonomy
# ---------------------------------------------------------------------------


@pytest.fixture
def failing_get_llm_client(monkeypatch):
    """Make client construction fail, as it does when no credentials exist."""
    async def _get(_model: str):
        raise ValueError("no credentials configured")

    monkeypatch.setattr("app.services.llm.get_llm_client", _get)


@pytest.mark.asyncio
async def test_discover_taxonomy_empty_contacts(fake_llm_client):
    result = await discover_taxonomy([])

    assert result == {}
    assert fake_llm_client.calls == []


@pytest.mark.asyncio
async def test_discover_taxonomy_client_construction_failure_returns_empty(
    failing_get_llm_client,
):
    result = await discover_taxonomy([{"full_name": "Alice"}])

    assert result == {}


@pytest.mark.asyncio
async def test_discover_taxonomy_valid_response(fake_llm_client):
    fake_llm_client.response = '{"Role": ["CEO", "CTO"], "Industry": ["Tech"]}'

    result = await discover_taxonomy([{"full_name": "Alice", "title": "CEO"}])

    assert "Role" in result
    assert "CEO" in result["Role"]
    assert "CTO" in result["Role"]
    assert "Industry" in result
    assert "Tech" in result["Industry"]

    call = fake_llm_client.last_call
    assert call is not None
    assert call["model"] == settings.LLM_MODEL_FAST
    assert call["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_discover_taxonomy_batching_60_contacts(fake_llm_client):
    """60 contacts with _BATCH_SIZE=50 should result in 2 API calls."""
    fake_llm_client.response = '{"Role": ["Engineer"]}'

    contacts = [{"full_name": f"Contact {i}"} for i in range(60)]

    result = await discover_taxonomy(contacts)

    assert len(fake_llm_client.calls) == 2
    assert "Role" in result
    assert "Engineer" in result["Role"]


@pytest.mark.asyncio
async def test_discover_taxonomy_first_batch_failure_raises(fake_llm_client):
    """If the first batch API call raises, discover_taxonomy must propagate the exception."""
    fake_llm_client.responses = [LLMError("API down", status_code=400)]

    with pytest.raises(LLMError, match="API down"):
        await discover_taxonomy([{"full_name": "Alice"}])


@pytest.mark.asyncio
async def test_discover_taxonomy_second_batch_failure_continues(fake_llm_client):
    """If only the second batch fails, partial results from the first batch are returned."""
    fake_llm_client.responses = [
        '{"Role": ["Engineer"]}',
        LLMError("second batch failed", status_code=400),
    ]

    contacts = [{"full_name": f"Contact {i}"} for i in range(60)]

    result = await discover_taxonomy(contacts)

    assert "Role" in result
    assert "Engineer" in result["Role"]


# ---------------------------------------------------------------------------
# assign_tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_tags_client_construction_failure_returns_empty(
    failing_get_llm_client,
):
    result = await assign_tags({"full_name": "Alice"}, {"Role": ["CEO"]})

    assert result == []


@pytest.mark.asyncio
async def test_assign_tags_returns_matching_tags(fake_llm_client):
    taxonomy = {"Role": ["CEO", "Founder"]}
    fake_llm_client.response = '{"tags": ["CEO", "Founder"], "new_tags": []}'

    result = await assign_tags(
        {"full_name": "Alice", "title": "CEO and Founder"},
        taxonomy,
    )

    assert "CEO" in result
    assert "Founder" in result

    call = fake_llm_client.last_call
    assert call is not None
    assert call["model"] == settings.LLM_MODEL_FAST
    assert call["max_tokens"] == 512


@pytest.mark.asyncio
async def test_assign_tags_filters_out_tags_not_in_taxonomy(fake_llm_client):
    taxonomy = {"Role": ["CEO"]}
    fake_llm_client.response = '{"tags": ["CEO", "Alien Overlord"], "new_tags": []}'

    result = await assign_tags({"full_name": "Alice"}, taxonomy)

    assert "CEO" in result
    assert "Alien Overlord" not in result


@pytest.mark.asyncio
async def test_assign_tags_case_insensitive_match_returns_canonical(fake_llm_client):
    """LLM returns 'ceo' (lowercase); taxonomy has 'CEO' — canonical form is returned."""
    taxonomy = {"Role": ["CEO", "Founder"]}
    fake_llm_client.response = '{"tags": ["ceo"], "new_tags": []}'

    result = await assign_tags({"full_name": "Alice"}, taxonomy)

    assert "CEO" in result
    assert "ceo" not in result


@pytest.mark.asyncio
async def test_assign_tags_api_failure_returns_empty_list(fake_llm_client):
    fake_llm_client.responses = [LLMError("API error", status_code=401)]

    result = await assign_tags({"full_name": "Alice"}, {"Role": ["CEO"]})

    assert result == []


@pytest.mark.asyncio
async def test_assign_tags_invalid_json_response_returns_empty_list(fake_llm_client):
    fake_llm_client.response = "not json at all"

    result = await assign_tags({"full_name": "Alice"}, {"Role": ["CEO"]})

    assert result == []


@pytest.mark.asyncio
async def test_assign_tags_uses_provided_client_not_factory(fake_llm_client):
    """When a client is passed in, get_llm_client must not be used."""
    taxonomy = {"Role": ["Engineer"]}
    provided = FakeLLMClient(response='{"tags": ["Engineer"], "new_tags": []}')

    result = await assign_tags(
        {"full_name": "Bob", "title": "Software Engineer"},
        taxonomy,
        client=provided,
    )

    assert "Engineer" in result
    assert len(provided.calls) == 1
    assert fake_llm_client.calls == []


@pytest.mark.asyncio
async def test_assign_tags_empty_tags_in_response(fake_llm_client):
    taxonomy = {"Role": ["CEO"]}
    fake_llm_client.response = '{"tags": [], "new_tags": []}'

    result = await assign_tags({"full_name": "Alice"}, taxonomy)

    assert result == []
