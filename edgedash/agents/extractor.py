import hashlib
from typing import Any

from edgedash import llm, storage
from edgedash.config import Config, load_config

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "required_skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Skills the role explicitly requires.",
        },
        "nice_to_have": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Preferred skills, not required.",
        },
        "seniority": {
            "type": "string",
            "enum": ["junior", "mid", "senior", "lead", "unknown"],
            "description": "Seniority level of the role.",
        },
        "years_required": {
            "type": ["integer", "null"],
            "description": "Years of experience required, or null if not stated.",
        },
        "remote_ok": {
            "type": ["boolean", "null"],
            "description": "True if remote work is allowed/stated, false if explicitly in-office, or null if unstated.",
        },
    },
    "required": [
        "required_skills",
        "nice_to_have",
        "seniority",
        "years_required",
        "remote_ok",
    ],
    "additionalProperties": False,
}

EXTRACTION_PROMPT_TEMPLATE = """You are an objective document reader analyzing a job listing description.

CRITICAL INSTRUCTIONS:
1. Extract ONLY information explicitly stated in the job description text.
2. Do NOT infer, guess, extrapolate, or speculate on unstated requirements.
3. Do NOT mention, evaluate, or compare against any candidate, profile, or score. You are reading a text document only.
4. If a field is not explicitly mentioned in the text:
   - required_skills: []
   - nice_to_have: []
   - seniority: "unknown"
   - years_required: null
   - remote_ok: null

Job Description:
---
{description}
---
"""


def compute_description_hash(description: str) -> str:
    cleaned = (description or "").strip()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def _normalize_skills(skills: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in skills:
        if isinstance(item, str):
            s = item.strip().lower()
            if s and s not in seen:
                seen.add(s)
                normalized.append(s)
    return normalized


def extract(listing: dict[str, Any], config: Config | None = None) -> dict[str, Any]:
    if config is None:
        config = load_config()

    description = str(listing.get("description") or listing.get("desc") or "")
    desc_hash = compute_description_hash(description)

    # 1. Check extraction cache FIRST
    cached = storage.get_extraction(config.db_path, desc_hash)
    if cached is not None:
        return cached

    # 2. Cache miss: Call LLM
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(description=description)
    raw_result = llm.complete_json(
        prompt=prompt,
        schema=EXTRACTION_SCHEMA,
        config=config,
    )

    # 3. Normalise skills and validate fields before storing
    raw_req = raw_result.get("required_skills")
    raw_nice = raw_result.get("nice_to_have")

    required_skills = _normalize_skills(raw_req if isinstance(raw_req, list) else [])
    nice_to_have = _normalize_skills(raw_nice if isinstance(raw_nice, list) else [])

    seniority = str(raw_result.get("seniority", "unknown")).lower()
    if seniority not in {"junior", "mid", "senior", "lead", "unknown"}:
        seniority = "unknown"

    years_required = raw_result.get("years_required")
    if years_required is not None and not isinstance(years_required, bool):
        try:
            years_required = int(years_required)
        except (ValueError, TypeError):
            years_required = None
    else:
        years_required = None

    raw_remote = raw_result.get("remote_ok")
    remote_ok = True if raw_remote is True else (False if raw_remote is False else None)

    extracted_data = {
        "required_skills": required_skills,
        "nice_to_have": nice_to_have,
        "seniority": seniority,
        "years_required": years_required,
        "remote_ok": remote_ok,
    }

    # 4. Save to cache
    storage.save_extraction(config.db_path, desc_hash, extracted_data)

    return extracted_data
