"""AI-powered tag discovery and assignment."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings
from app.services import llm

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50


def _parse_json_response(raw: str) -> Any:
    """Parse JSON from LLM response, handling markdown code fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("_parse_json_response: could not parse: %r", raw[:200])
        return None


def _sanitize(value: str, max_len: int = 200) -> str:
    """Sanitize a user-supplied string before interpolating into an LLM prompt.

    Wraps the value in structural delimiters so injected instructions inside
    contact fields cannot be misread as system-level instructions.
    Truncates to max_len and strips control characters.
    """
    # Truncate and strip control chars (keep newlines for bios)
    cleaned = value[:max_len].replace("\r", "")
    return f"<value>{cleaned}</value>"


def _build_contact_summary(contact_data: dict) -> str:
    """Build a concise text summary of a contact for the LLM."""
    parts = []
    if contact_data.get("full_name"):
        parts.append(f"Name: {_sanitize(contact_data['full_name'], 100)}")
    if contact_data.get("title"):
        parts.append(f"Title: {_sanitize(contact_data['title'], 100)}")
    if contact_data.get("company"):
        parts.append(f"Company: {_sanitize(contact_data['company'], 100)}")
    if contact_data.get("twitter_bio"):
        parts.append(f"Twitter bio: {_sanitize(contact_data['twitter_bio'], 200)}")
    if contact_data.get("telegram_bio"):
        parts.append(f"Telegram bio: {_sanitize(contact_data['telegram_bio'], 200)}")
    if contact_data.get("notes"):
        # Filter out bio sentinel lines
        notes = contact_data["notes"]
        lines = [l for l in notes.splitlines() if not l.startswith("__twitter_bio__:")]
        trimmed = "\n".join(lines)[:300]
        if trimmed.strip():
            parts.append(f"Notes: {_sanitize(trimmed, 300)}")
    if contact_data.get("tags"):
        tags_str = ", ".join(str(t)[:50] for t in contact_data["tags"][:20])
        parts.append(f"Existing tags: {_sanitize(tags_str, 500)}")
    if contact_data.get("location"):
        parts.append(f"Location: {_sanitize(contact_data['location'], 100)}")
    if contact_data.get("interaction_topics"):
        topics = [str(t)[:100] for t in contact_data["interaction_topics"][:10]]
        topics_str = ", ".join(topics)
        parts.append(f"Interaction topics: {_sanitize(topics_str, 500)}")
    return "\n".join(parts) if parts else "(minimal data)"


async def discover_taxonomy(
    contacts_summary: list[dict],
    existing_taxonomy: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """Phase 0+1: Discover a minimal tag taxonomy from contacts.

    When *existing_taxonomy* is provided (Phase 0 / vocabulary priming), the LLM
    is instructed to extend rather than duplicate the existing tags.

    Args:
        contacts_summary: List of dicts with contact fields (name, title, company, bios, etc.)
        existing_taxonomy: Previously approved taxonomy to anchor against (avoids drift across batches).

    Returns:
        Dict mapping category names to lists of tag strings.
    """
    if not contacts_summary:
        return {}

    try:
        client = await llm.get_llm_client(settings.LLM_MODEL_FAST)
    except Exception:
        logger.exception("discover_taxonomy: could not construct LLM client.")
        return {}

    # Batch contacts
    batches: list[list[dict]] = []
    for i in range(0, len(contacts_summary), _BATCH_SIZE):
        batches.append(contacts_summary[i:i + _BATCH_SIZE])

    all_categories: dict[str, set[str]] = {}

    # Phase 0: vocabulary priming preamble (anchors new batches to existing taxonomy)
    phase0_preamble = ""
    if existing_taxonomy:
        existing_json = json.dumps(existing_taxonomy, indent=2)
        phase0_preamble = (
            "Existing taxonomy (do not duplicate these, only extend if genuinely "
            "new patterns appear):\n"
            f"{existing_json}\n\n"
            "Now analyse this new batch and propose ONLY tags not already covered above.\n\n"
        )

    for batch_idx, batch in enumerate(batches):
        summaries = []
        for i, c in enumerate(batch):
            summaries.append(f"Contact {i + 1}:\n{_build_contact_summary(c)}")

        prompt = (
            "You are analysing a batch of professional contacts to discover a MINIMAL "
            "tag taxonomy.\n\n"
            + phase0_preamble
            + "Contacts:\n\n"
            + "\n---\n".join(summaries)
            + "\n\n"
            "Rules:\n"
            "- Aim for FEWER, BROADER tags. A good taxonomy has 30-60 tags total, not 200.\n"
            "- A tag must apply to AT LEAST 3 contacts in this batch to be proposed. "
            "If it only fits 1-2 people, skip it.\n"
            "- Prefer role clusters over job titles: \"Product\" beats \"Senior Product Manager\" "
            "and \"VP of Product\" separately.\n"
            "- Events: only include if the event recurs or has >5 attendees visible in this batch. "
            "Skip one-off mentions.\n"
            "- Geography: city/region only, not neighbourhood.\n"
            "- No tags that are just a person's employer or a one-off project name.\n\n"
            "Categories: Role/Expertise, Industry, Interests, Cohort/Program, Geography, Events.\n\n"
            "Return ONLY a JSON object: keys are category names, values are arrays of tags."
        )

        try:
            raw = await llm.complete_with_retry(
                client,
                model=settings.LLM_MODEL_FAST,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
                timeout=settings.LLM_TIMEOUT_TAXONOMY,
            )
            parsed = _parse_json_response(raw)

            if isinstance(parsed, dict):
                for category, tags in parsed.items():
                    if isinstance(tags, list):
                        if category not in all_categories:
                            all_categories[category] = set()
                        for tag in tags:
                            if isinstance(tag, str) and tag.strip():
                                all_categories[category].add(tag.strip())
        except Exception:
            logger.exception("discover_taxonomy: batch %d/%d failed.", batch_idx + 1, len(batches))
            # If the first batch fails, re-raise so the caller can surface the error
            if batch_idx == 0 and not all_categories:
                raise

    # Convert sets to sorted lists
    return {cat: sorted(tags) for cat, tags in all_categories.items() if tags}


async def deduplicate_taxonomy(
    raw_taxonomy: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Post-discovery pass: merge near-duplicate tags and categories via LLM.

    Examples of merges:
    - "COO" + "Chief Operating Officer" → "COO"
    - "VC/Investment" + "Venture Capital" → "Venture Capital"
    - Categories "Role/Expertise" + "Role" → "Role/Expertise"
    """
    # Guard: skip if taxonomy is empty or small (≤10 tags total)
    total_tags = sum(len(tags) for tags in raw_taxonomy.values())
    if total_tags <= 10:
        logger.info("deduplicate_taxonomy: skipping (only %d tags).", total_tags)
        return raw_taxonomy

    taxonomy_json = json.dumps(raw_taxonomy, indent=2)

    prompt = (
        "You are cleaning a tag taxonomy in two passes.\n\n"
        "PASS 1 - Merge duplicates:\n"
        "1. Merge overlapping categories aggressively "
        "(e.g. \"Role/Title\" + \"Role/Expertise\" → \"Role\"). "
        "Combine all tags from merged categories into the surviving one\n"
        "2. Merge abbreviations/synonyms, keep shorter canonical form "
        "(e.g. \"COO\" + \"Chief Operating Officer\" → \"COO\")\n"
        "3. Merge seniority variants "
        "(\"Junior Engineer\" + \"Senior Engineer\" → \"Engineer\")\n"
        "4. One tag per concept across all categories\n\n"
        "PASS 2 - Prune narrow tags:\n"
        "Remove any tag that:\n"
        "- Describes a single named event with no obvious recurrence\n"
        "- Is a job title so specific it fits <2% of a typical contact list "
        "(e.g. \"Director of Revenue Operations EMEA\")\n"
        "- Duplicates a broader tag already present "
        "(if \"Startup Founder\" exists, remove \"First-time Founder\")\n"
        "- Is a company name or personal project name\n\n"
        f"Input taxonomy:\n{taxonomy_json}\n\n"
        "Return ONLY the cleaned JSON object. Same format: "
        "keys are category names, values are arrays of tag strings."
    )

    try:
        client = await llm.get_llm_client(settings.LLM_MODEL_FAST)
        raw = await llm.complete_with_retry(
            client,
            model=settings.LLM_MODEL_FAST,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
            timeout=settings.LLM_TIMEOUT_TAXONOMY,
        )
        parsed = _parse_json_response(raw)

        if isinstance(parsed, dict) and all(
            isinstance(v, list) and all(isinstance(t, str) for t in v)
            for v in parsed.values()
        ):
            deduped_total = sum(len(tags) for tags in parsed.values())
            logger.info(
                "deduplicate_taxonomy: %d categories/%d tags → %d categories/%d tags",
                len(raw_taxonomy),
                total_tags,
                len(parsed),
                deduped_total,
            )
            return parsed

        logger.warning("deduplicate_taxonomy: unexpected response structure, returning original.")
        return raw_taxonomy
    except Exception:
        logger.exception("deduplicate_taxonomy: LLM call failed, returning original taxonomy.")
        return raw_taxonomy


async def assign_tags(
    contact_data: dict,
    taxonomy: dict[str, list[str]],
    *,
    client: llm.LLMClient | None = None,
) -> list[str]:
    """Phase 2: Assign tags to a single contact from the approved taxonomy.

    Args:
        contact_data: Dict with contact fields.
        taxonomy: The approved taxonomy (category -> tags).
        client: Optional pre-resolved LLMClient to reuse across contacts.
            When omitted, the memoized adapter for ``LLM_MODEL_FAST`` is used.

    Returns:
        List of tag strings to assign.
    """
    # Flatten taxonomy for prompt
    taxonomy_lines = []
    for category, tags in taxonomy.items():
        taxonomy_lines.append(f"  {category}: {', '.join(tags)}")
    taxonomy_text = "\n".join(taxonomy_lines)

    summary = _build_contact_summary(contact_data)

    prompt = (
        "You are tagging a professional contact using an approved taxonomy.\n\n"
        f"Taxonomy:\n{taxonomy_text}\n\n"
        f"Contact:\n{summary}\n\n"
        "Instructions:\n"
        "- Select tags that CLEARLY apply. When in doubt, omit.\n"
        "- Maximum 8 tags total per contact.\n"
        "- Prioritise: Role/Expertise first, then Industry, then everything else.\n"
        "- Only suggest a NEW tag (prefix \"NEW: \") if it would apply to many other "
        "contacts too, not just this one. Maximum 1 new tag suggestion.\n\n"
        "Return ONLY a JSON object:\n"
        "- \"tags\": array of up to 8 tag strings from the taxonomy\n"
        "- \"new_tags\": array of 0-1 new tag suggestions"
    )

    try:
        if client is None:
            client = await llm.get_llm_client(settings.LLM_MODEL_FAST)
        raw = await llm.complete_with_retry(
            client,
            model=settings.LLM_MODEL_FAST,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
            timeout=settings.LLM_TIMEOUT_TAG_ASSIGNMENT,
        )
        parsed = _parse_json_response(raw)

        if isinstance(parsed, dict):
            tags = parsed.get("tags", [])
            if isinstance(tags, list):
                # Validate tags exist in taxonomy
                all_valid_tags = set()
                for tag_list in taxonomy.values():
                    all_valid_tags.update(tag_list)

                result = []
                for tag in tags:
                    if isinstance(tag, str) and tag.strip():
                        # Case-insensitive match
                        matched = next(
                            (t for t in all_valid_tags if t.lower() == tag.strip().lower()),
                            None,
                        )
                        if matched:
                            result.append(matched)
                return result
        return []
    except Exception:
        logger.exception("assign_tags: Anthropic API call failed.")
        return []


def merge_tags(existing: list[str] | None, new_tags: list[str]) -> list[str]:
    """Merge new AI tags into existing tags, deduplicating case-insensitively.

    Never removes existing tags — only appends.
    """
    existing = existing or []
    existing_lower = {t.lower() for t in existing}
    merged = list(existing)
    for tag in new_tags:
        if tag.lower() not in existing_lower:
            merged.append(tag)
            existing_lower.add(tag.lower())
    return merged
