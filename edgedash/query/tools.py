"""Deterministic query tool registry for EdgeDash natural language queries.

All tools are read-only, parameterised, and read through the storage module (Rule 2).
All model-supplied inputs are clamped and validated (Rule 41). No LLM inside this file.
"""

from typing import Any, Callable
from edgedash import skills, storage

TOOLS: dict[str, dict[str, Any]] = {}


def tool(name: str, description: str, parameters: dict[str, Any]) -> Callable[..., Any]:
    """Decorator registering query tool functions in the TOOLS registry."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        TOOLS[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "func": func,
        }
        func.__tool_name__ = name
        func.__tool_description__ = description
        func.__tool_parameters__ = parameters
        return func

    return decorator


def _clamp_int(val: Any, default: int, min_val: int, max_val: int) -> int:
    try:
        v = int(val)
    except (ValueError, TypeError):
        v = default
    return max(min_val, min(v, max_val))


def _resolve_canonical_skill(skill: str, db_path: str) -> str | None:
    if not isinstance(skill, str) or not skill.strip():
        return None
    canon_skill = skills.canonical(skill.strip())
    if not canon_skill:
        return None

    present_skills = storage.get_present_skills(db_path)
    if canon_skill.lower() not in present_skills:
        return None
    return canon_skill


@tool(
    name="companies_hiring",
    description="List companies with active job listings posted within the last N days, along with listing counts. Use when asked which companies are hiring or active recently.",
    parameters={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Lookback window in days (1 to 90, default 7)",
                "default": 7,
            }
        },
        "required": [],
    },
)
def companies_hiring(days: int = 7, db_path: str = "edgedash.db") -> dict[str, Any]:
    clamped_days = _clamp_int(days, default=7, min_val=1, max_val=90)
    rows = storage.query_companies_hiring(db_path=db_path, days=clamped_days)
    total_listings = sum(int(r.get("listing_count", 0)) for r in rows)
    summary = f"{total_listings} listings from {len(rows)} hiring companies in the last {clamped_days} days"
    return {"summary": summary, "rows": rows}


@tool(
    name="best_matches",
    description="Retrieve the highest-scoring job listings with fit score, title, company, and reason. Use when asked for top matches, best job listings, or highest fit scores.",
    parameters={
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
                "description": "Number of top matching listings to return (1 to 25, default 10)",
                "default": 10,
            }
        },
        "required": [],
    },
)
def best_matches(n: int = 10, db_path: str = "edgedash.db") -> dict[str, Any]:
    clamped_n = _clamp_int(n, default=10, min_val=1, max_val=25)
    rows = storage.query_best_matches(db_path=db_path, limit=clamped_n)
    summary = f"Top {len(rows)} highest-scoring job matches"
    return {"summary": summary, "rows": rows}


@tool(
    name="top_gaps",
    description="Retrieve top skill gaps ranked by opportunity cost, showing listings blocked and mean scores. Use when asked for missing skills, biggest skill gaps, or career blockers.",
    parameters={
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
                "description": "Number of top skill gaps to return (1 to 25, default 5)",
                "default": 5,
            }
        },
        "required": [],
    },
)
def top_gaps(n: int = 5, db_path: str = "edgedash.db") -> dict[str, Any]:
    clamped_n = _clamp_int(n, default=5, min_val=1, max_val=25)
    rows = storage.query_top_gaps(db_path=db_path, limit=clamped_n)
    summary = f"Top {len(rows)} skill gaps by opportunity cost from last passing cycle"
    return {"summary": summary, "rows": rows}


@tool(
    name="gap_detail",
    description="Drill down into a specific skill gap to list the exact job listings blocked by that named skill. Use when asking which specific jobs require or are blocked by a skill.",
    parameters={
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "The target skill name to inspect (e.g., 'kubernetes', 'python')",
            }
        },
        "required": ["skill"],
    },
)
def gap_detail(skill: str, db_path: str = "edgedash.db") -> dict[str, Any]:
    canon_skill = _resolve_canonical_skill(skill, db_path)
    if not canon_skill:
        return {
            "summary": f"No data found for skill '{skill}' in database",
            "rows": [],
        }

    rows = storage.query_gap_detail(db_path=db_path, canonical_skill=canon_skill)
    summary = f"{len(rows)} listings blocked by skill '{canon_skill}'"
    return {"summary": summary, "rows": rows}


@tool(
    name="trend",
    description="Track skill gap opportunity cost change over N weeks from historical snapshots. Use when asked about trends, changes over time, or evolving skill demands.",
    parameters={
        "type": "object",
        "properties": {
            "weeks": {
                "type": "integer",
                "description": "Number of weeks back for trend lookback (1 to 12, default 3)",
                "default": 3,
            }
        },
        "required": [],
    },
)
def trend(weeks: int = 3, db_path: str = "edgedash.db") -> dict[str, Any]:
    clamped_weeks = _clamp_int(weeks, default=3, min_val=1, max_val=12)
    rows = storage.query_gap_trend(db_path=db_path, weeks=clamped_weeks)
    summary = f"Skill gap opportunity cost change over last {clamped_weeks} weeks across snapshots"
    return {"summary": summary, "rows": rows}


@tool(
    name="listing_count",
    description="Get overall database totals including total listings, scored count, unscored count, and newest listing date. Use when asked for overall stats, counts, or listing volume.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def listing_count(db_path: str = "edgedash.db") -> dict[str, Any]:
    rows = storage.query_listing_count(db_path=db_path)
    info = rows[0] if rows else {}
    total = info.get("total_listings", 0)
    scored = info.get("scored_listings", 0)
    unscored = info.get("unscored_listings", 0)
    newest = info.get("newest_listing_date", "N/A")
    summary = f"Total listing metrics: {total} listings, {scored} scored, {unscored} unscored, newest on {newest}"
    return {"summary": summary, "rows": rows}


@tool(
    name="skill_demand",
    description="Check how frequently a named skill appears as required vs nice-to-have across all extractions. Use when asking how in-demand a skill is or required vs optional frequency.",
    parameters={
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "The target skill name (e.g., 'python', 'docker')",
            }
        },
        "required": ["skill"],
    },
)
def skill_demand(skill: str, db_path: str = "edgedash.db") -> dict[str, Any]:
    canon_skill = _resolve_canonical_skill(skill, db_path)
    if not canon_skill:
        return {
            "summary": f"No data found for skill '{skill}' in database",
            "rows": [],
        }

    rows = storage.query_skill_demand(db_path=db_path, canonical_skill=canon_skill)
    info = rows[0] if rows else {}
    req = info.get("required_count", 0)
    nice = info.get("nice_to_have_count", 0)
    summary = f"Skill '{canon_skill}' demand: {req} required, {nice} nice-to-have"
    return {"summary": summary, "rows": rows}
