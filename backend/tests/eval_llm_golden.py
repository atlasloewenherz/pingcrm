"""Golden eval harness for the five LLM-backed services.

Each fixture under ``tests/fixtures/golden/`` supplies a deterministic input,
a recorded response (used in fake mode), and the output shape/keywords the
service must produce. The harness drives the *services* — not the raw
adapters — through ``get_llm_client`` so the factory, model-role selection,
and the service's own parsing/fallback logic are all exercised.

Two modes:

* **fake** (default): ``get_llm_client`` is replaced with a
  ``FakeLLMClient`` returning the fixture's recorded response. No API key and
  no network access are required, so this runs locally and in the regular test
  suite.
* **live**: when ``LLM_API_KEY`` or ``ANTHROPIC_API_KEY`` is present in the
  environment the real memoized adapter is used. This is the CI gate mode.
  ``LLM_EVAL_MODE=fake|live`` overrides the auto-detection explicitly.

Run with ``pytest -m eval tests/eval_llm_golden.py``.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import settings

pytestmark = pytest.mark.eval

# The eval harness is deliberately database-free: the CI gate runs it without a
# Postgres service. These no-op overrides shadow the autouse database fixtures
# in ``tests/conftest.py`` for this module only.
@pytest.fixture(scope="session")
def _schema():
    yield


@pytest.fixture
def setup_database():
    yield None


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "golden"

FIXTURE_FILES = sorted(FIXTURE_DIR.glob("*.json"))
FIXTURES = {path.stem: json.loads(path.read_text()) for path in FIXTURE_FILES}

TASKS = tuple(sorted(FIXTURES))


def _eval_mode() -> str:
    """Resolve ``fake`` vs ``live``.

    An explicit ``LLM_EVAL_MODE`` wins; otherwise the presence of an API key
    in the *environment* (not the app's ``.env``) selects live mode so a
    developer's local ``.env`` never accidentally spends API credits.
    """
    explicit = os.environ.get("LLM_EVAL_MODE", "").strip().lower()
    if explicit in {"fake", "live"}:
        return explicit
    if os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
        return "live"
    return "fake"


@pytest.fixture
def eval_mode() -> str:
    return _eval_mode()


@pytest.fixture
def recorded_models(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    """Record every model passed to ``get_llm_client`` during a test.

    In fake mode the factory returns a ``FakeLLMClient`` loaded with the
    fixture's recorded response. In live mode it delegates to the real
    memoized factory so an actual provider is exercised.
    """
    from app.services import llm

    task = request.node.callspec.params["task"]
    models: list[str] = []
    original = llm.get_llm_client

    if _eval_mode() == "live":
        async def _get(model: str) -> llm.LLMClient:
            models.append(model)
            return await original(model)
    else:
        from tests.fakes import FakeLLMClient

        fake = FakeLLMClient(response=FIXTURES[task]["fake_response"])

        async def _get(model: str) -> llm.LLMClient:
            models.append(model)
            return fake

    monkeypatch.setattr(llm, "get_llm_client", _get, raising=False)
    return models


class _Result:
    """Minimal SQLAlchemy result double for the message composer."""

    def __init__(self, *, scalar: Any = None, rows: list[Any] | None = None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    """Returns the contact first, then the interaction rows."""

    def __init__(self, contact: Any, interactions: list[Any]) -> None:
        self._results = [_Result(scalar=contact), _Result(rows=interactions)]

    async def execute(self, *_args: Any, **_kwargs: Any) -> _Result:
        return self._results.pop(0)


def _compose_contact(spec: dict[str, Any]) -> SimpleNamespace:
    last_interaction = datetime.now(UTC) - timedelta(
        days=spec.get("last_interaction_days_ago", 200)
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        full_name=spec.get("full_name"),
        given_name=spec.get("given_name"),
        company=spec.get("company"),
        title=spec.get("title"),
        relationship_score=spec.get("relationship_score", 5),
        last_interaction_at=last_interaction,
        twitter_bio=spec.get("twitter_bio"),
        twitter_handle=spec.get("twitter_handle"),
        telegram_bio=spec.get("telegram_bio"),
        linkedin_headline=spec.get("linkedin_headline"),
        linkedin_bio=spec.get("linkedin_bio"),
    )


def _compose_interactions(specs: list[dict[str, Any]]) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            content_preview=spec.get("content_preview"),
            direction=spec.get("direction", "inbound"),
            platform=spec.get("platform", "email"),
            occurred_at=datetime.now(UTC) - timedelta(days=spec.get("days_ago", 30)),
        )
        for spec in specs
    ]


async def _invoke(task: str, payload: dict[str, Any]) -> Any:
    if task == "bio_extractor":
        from app.services.bio_extractor import extract_from_bios

        return await extract_from_bios(**payload)

    if task == "event_classifier":
        from app.services.event_classifier import classify_tweet

        return await classify_tweet(
            tweet_text=payload["tweet_text"],
            contact_name=payload["contact_name"],
        )

    if task == "auto_tagger":
        from app.services.auto_tagger import assign_tags

        return await assign_tags(payload["contact_data"], payload["taxonomy"])

    if task == "message_composer":
        from app.services.message_composer import compose_followup_message

        contact = _compose_contact(payload["contact"])
        interactions = _compose_interactions(payload.get("interactions", []))
        db = _FakeSession(contact, interactions)
        return await compose_followup_message(
            contact_id=contact.id,
            trigger_type=payload["trigger_type"],
            event_summary=payload.get("event_summary"),
            db=db,  # type: ignore[arg-type]
        )

    if task == "meeting_prep":
        from app.services.meeting_prep import generate_talking_points

        return await generate_talking_points(
            payload["briefs"],
            payload["meeting_title"],
        )

    raise AssertionError(f"unknown eval task: {task}")


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _assert_keyword_groups(haystack: str, groups: list[list[str]]) -> None:
    low = haystack.lower()
    for group in groups:
        assert any(keyword.lower() in low for keyword in group), (
            f"expected one of {group!r} in output: {haystack!r}"
        )


def _assert_output(task: str, output: Any, expected: dict[str, Any]) -> None:
    kind = expected["type"]

    if kind == "object":
        assert isinstance(output, dict), f"{task}: expected dict, got {type(output)!r}"
        for key in expected.get("required_keys", []):
            assert key in output, f"{task}: missing required key {key!r} in {output!r}"
        allowed = expected.get("allowed_keys")
        if allowed is not None:
            unexpected = set(output) - set(allowed)
            assert not unexpected, f"{task}: unexpected keys {sorted(unexpected)!r}"
        if "valid_event_types" in expected:
            assert output["event_type"] in expected["valid_event_types"]
        if "event_type" in expected:
            assert output["event_type"] == expected["event_type"]
        if "confidence_min" in expected:
            assert output["confidence"] >= expected["confidence_min"]
        _assert_keyword_groups(_flatten(output), expected.get("keyword_groups", []))

    elif kind == "list":
        assert isinstance(output, list), f"{task}: expected list, got {type(output)!r}"
        assert len(output) >= expected.get("min_items", 0), f"{task}: too few items: {output!r}"
        assert len(output) <= expected.get("max_items", 10**9), f"{task}: too many items: {output!r}"
        _assert_keyword_groups(_flatten(output), expected.get("keyword_groups", []))

    elif kind == "text":
        assert isinstance(output, str), f"{task}: expected str, got {type(output)!r}"
        assert len(output) >= expected.get("min_length", 0), f"{task}: output too short: {output!r}"
        for forbidden in expected.get("forbidden_substrings", []):
            assert forbidden not in output, f"{task}: forbidden substring {forbidden!r} in {output!r}"
        _assert_keyword_groups(output, expected.get("keyword_groups", []))

    else:  # pragma: no cover - fixture authoring error
        raise AssertionError(f"{task}: unknown expected type {kind!r}")


@pytest.mark.parametrize("task", TASKS)
async def test_golden_eval(task: str, recorded_models: list[str], eval_mode: str) -> None:
    fixture = FIXTURES[task]
    assert fixture["task"] == task

    output = await _invoke(task, fixture["input"])

    _assert_output(task, output, fixture["expected"])

    # The service must have asked the factory for its documented model role.
    expected_model = getattr(settings, fixture["model_role"])
    assert recorded_models, f"{task}: service never called get_llm_client"
    assert recorded_models[-1] == expected_model, (
        f"{task}: requested {recorded_models[-1]!r}, expected {expected_model!r}"
    )

    print(f"[llm-eval] task={task} mode={eval_mode} output={output!r}")
