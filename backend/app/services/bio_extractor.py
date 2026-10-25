"""AI-powered structured data extraction from contact bios."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings
from app.services import llm

logger = logging.getLogger(__name__)

_LLM_TIMEOUT = 30.0


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
        logger.warning("bio_extractor: could not parse LLM response: %r", raw[:200])
        return None


async def extract_from_bios(
    *,
    full_name: str | None = None,
    given_name: str | None = None,
    family_name: str | None = None,
    title: str | None = None,
    company: str | None = None,
    twitter_bio: str | None = None,
    telegram_bio: str | None = None,
    linkedin_bio: str | None = None,
    linkedin_headline: str | None = None,
) -> dict[str, str]:
    """Extract structured contact and company info from bios.

    Returns a dict with any of these keys (only non-empty extractions):
        - given_name, family_name
        - title
        - company, company_website, company_industry, company_location
    """
    # Build context block
    parts: list[str] = []
    if full_name:
        parts.append(f"Full name: {full_name}")
    if given_name:
        parts.append(f"First name: {given_name}")
    if family_name:
        parts.append(f"Last name: {family_name}")
    if title:
        parts.append(f"Current title: {title}")
    if company:
        parts.append(f"Current company: {company}")
    if twitter_bio:
        parts.append(f"Twitter bio: {twitter_bio}")
    if telegram_bio:
        parts.append(f"Telegram bio: {telegram_bio}")
    if linkedin_headline:
        parts.append(f"LinkedIn headline: {linkedin_headline}")
    if linkedin_bio:
        parts.append(f"LinkedIn bio: {linkedin_bio}")

    if not any([twitter_bio, telegram_bio, linkedin_bio, linkedin_headline, full_name]):
        return {}

    contact_info = "\n".join(parts)

    prompt = f"""Extract structured information from this contact's profile data.

<contact>
{contact_info}
</contact>

Rules:
1. If the full name contains separators like "|", "/", "—", "at", or similar patterns that indicate "Name | Company" or "Name / Role at Company", split them into the correct fields.
2. Extract the person's current job title and company from bios.
3. If a company website URL is mentioned in any bio, extract it.
4. If the company's industry can be clearly inferred, include it.
5. If a location is mentioned, extract it.
6. Only return fields you are confident about. Omit uncertain fields.
7. For given_name and family_name, return the cleaned personal name only (no company/role).

Return JSON only, no explanation. Use exactly these keys (omit any that are empty/unknown):
{{
  "given_name": "first name",
  "family_name": "last name",
  "title": "job title",
  "company": "company name",
  "company_website": "https://...",
  "company_industry": "industry",
  "company_location": "city, country"
}}"""

    client = await llm.get_llm_client(settings.LLM_MODEL_FAST)
    raw = await llm.complete_with_retry(
        client,
        model=settings.LLM_MODEL_FAST,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
        timeout=_LLM_TIMEOUT,
    )

    parsed = _parse_json_response(raw)
    if not isinstance(parsed, dict):
        return {}

    # Filter to only non-empty string values with known keys
    allowed_keys = {
        "given_name", "family_name", "title", "company",
        "company_website", "company_industry", "company_location",
    }
    return {
        k: str(v).strip()
        for k, v in parsed.items()
        if k in allowed_keys and v and str(v).strip()
    }
