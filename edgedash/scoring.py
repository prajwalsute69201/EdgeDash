"""
edgedash/scoring.py

Deterministic Scorer logic. Pure functions only.
NO model calls in this file. No network. No imports from llm.py.
"""

from datetime import datetime, timezone
from typing import Any
from edgedash.config import Config

SENIORITY_BANDS = ["junior", "mid", "senior", "lead"]


def _get_candidate_skills(config: Config) -> set[str]:
    raw_skills = getattr(config, "skills", None) or getattr(config, "my_skills", [])
    return {s.strip().lower() for s in raw_skills if isinstance(s, str) and s.strip()}


def _get_target_city(config: Config) -> str:
    city = getattr(config, "target_city", "Dubai")
    if isinstance(city, list) and city:
        return str(city[0]).strip().lower()
    return str(city).strip().lower()


def _get_target_seniority(config: Config) -> str:
    sen = getattr(config, "target_seniority", None)
    if sen:
        return str(sen).strip().lower()
    exp = getattr(config, "experience_years", 0)
    if exp <= 2:
        return "junior"
    elif exp <= 5:
        return "mid"
    elif exp <= 8:
        return "senior"
    return "lead"


def compute_skill_match(
    facts: dict[str, Any], candidate_skills: set[str]
) -> tuple[float, list[str], int, int]:
    req_skills = [s.strip().lower() for s in facts.get("required_skills", []) if s]
    nice_skills = [s.strip().lower() for s in facts.get("nice_to_have", []) if s]

    missing_required = [s for s in req_skills if s not in candidate_skills]
    matched_required = len(req_skills) - len(missing_required)
    matched_nice = sum(1 for s in nice_skills if s in candidate_skills)

    req_total = len(req_skills)
    nice_total = len(nice_skills)

    total_possible = req_total + (1.0 / 3.0) * nice_total
    total_earned = matched_required + (1.0 / 3.0) * matched_nice

    if total_possible == 0:
        # Handle the empty-required-skills case explicitly — do not divide by zero
        skill_score = 1.0
    else:
        skill_score = total_earned / total_possible

    return skill_score, missing_required, matched_required, req_total


def compute_seniority_fit(facts: dict[str, Any], target_seniority: str) -> float:
    fact_seniority = str(facts.get("seniority") or "unknown").strip().lower()
    if fact_seniority not in SENIORITY_BANDS or target_seniority not in SENIORITY_BANDS:
        return 0.5

    idx1 = SENIORITY_BANDS.index(fact_seniority)
    idx2 = SENIORITY_BANDS.index(target_seniority)
    distance = abs(idx1 - idx2)

    if distance == 0:
        return 1.0
    elif distance == 1:
        return 0.6
    elif distance == 2:
        return 0.25
    else:
        return 0.0


def compute_location_fit(
    listing: dict[str, Any], facts: dict[str, Any], target_city: str
) -> float:
    remote_ok = facts.get("remote_ok")
    if remote_ok is True:
        return 1.0

    location = str(listing.get("location") or facts.get("location") or "").strip().lower()
    if not location or "unknown" in location:
        return 0.5

    if target_city and target_city in location:
        return 1.0

    if "remote" in location:
        return 1.0

    return 0.1



def compute_recency(listing: dict[str, Any]) -> tuple[float, float | None]:
    raw_posted = listing.get("posted_at") or listing.get("posted")
    if not raw_posted:
        return 0.5, None

    dt: datetime | None = None
    if isinstance(raw_posted, datetime):
        dt = raw_posted
    elif isinstance(raw_posted, str):
        cleaned = raw_posted.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(cleaned)
        except ValueError:
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
                try:
                    dt = datetime.strptime(raw_posted, fmt)
                    break
                except ValueError:
                    pass

    if dt is None:
        return 0.5, None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    days_old = (now - dt).total_seconds() / 86400.0
    if days_old < 0:
        days_old = 0.0

    if days_old >= 30.0:
        recency_score = 0.0
    else:
        recency_score = 1.0 - (days_old / 30.0)

    return recency_score, days_old


def build_reason(
    components: dict[str, float],
    facts: dict[str, Any],
    config: Config,
    missing_skills: list[str] | None = None,
    matched_req_count: int | None = None,
    total_req_count: int | None = None,
    days_old: float | None = None,
    listing: dict[str, Any] | None = None,
) -> str:
    if listing is None:
        listing = {}

    parts = []

    # 1. Skills summary
    if total_req_count is None:
        candidate_skills = _get_candidate_skills(config)
        _, missing_skills, matched_req_count, total_req_count = compute_skill_match(
            facts, candidate_skills
        )

    if total_req_count > 0:
        parts.append(f"{matched_req_count}/{total_req_count} required skills")
    else:
        parts.append("no required skills listed")

    # 2. Seniority summary
    fact_sen = str(facts.get("seniority") or "unknown").strip().lower()
    target_sen = _get_target_seniority(config)
    if components.get("seniority_fit", 0.0) >= 0.6:
        parts.append("seniority fits")
    else:
        parts.append(f"{fact_sen} (target: {target_sen})")

    # 3. Location summary
    if facts.get("remote_ok") is True or "remote" in str(listing.get("location", "")).lower():
        parts.append("remote")
    elif components.get("location_fit", 0.0) == 1.0:
        parts.append("local")
    elif components.get("location_fit", 0.0) == 0.5:
        parts.append("location unstated")
    else:
        parts.append("non-remote")

    # 4. Recency summary
    if days_old is None and listing:
        _, days_old = compute_recency(listing)

    if days_old is not None:
        int_days = int(days_old)
        if int_days == 0:
            parts.append("posted today")
        else:
            parts.append(f"posted {int_days}d ago")
    else:
        parts.append("posted date unknown")

    # 5. Missing skills gap
    if missing_skills:
        gap_str = ", ".join(missing_skills)
        parts.append(f"gap: {gap_str}")

    return " · ".join(parts)


def score_listing(
    listing: dict[str, Any],
    facts: dict[str, Any],
    config: Config,
    widen_distribution: bool = False,
) -> dict[str, Any]:
    candidate_skills = _get_candidate_skills(config)
    target_city = _get_target_city(config)
    target_seniority = _get_target_seniority(config)

    # Component weights read from config (with defaults)
    w_skill = float(getattr(config, "weight_skill_match", 0.45))
    w_seniority = float(getattr(config, "weight_seniority_fit", 0.25))
    w_location = float(getattr(config, "weight_location_fit", 0.15))
    w_recency = float(getattr(config, "weight_recency", 0.15))

    skill_score, missing_skills, matched_req, total_req = compute_skill_match(
        facts, candidate_skills
    )
    seniority_score = compute_seniority_fit(facts, target_seniority)
    location_score = compute_location_fit(listing, facts, target_city)
    recency_score, days_old = compute_recency(listing)

    components = {
        "skill_match": round(skill_score, 4),
        "seniority_fit": round(seniority_score, 4),
        "location_fit": round(location_score, 4),
        "recency": round(recency_score, 4),
    }

    total_weight = w_skill + w_seniority + w_location + w_recency
    if total_weight <= 0:
        total_weight = 1.0

    weighted_sum = (
        w_skill * skill_score
        + w_seniority * seniority_score
        + w_location * location_score
        + w_recency * recency_score
    ) / total_weight

    if widen_distribution:
        # Contrast expansion around 0.5 midpoint to stretch score distribution
        # Pushes scores above 0.5 higher and scores below 0.5 lower
        weighted_sum = 0.5 + 1.6 * (weighted_sum - 0.5)

    final_score = int(round(max(0.0, min(1.0, weighted_sum)) * 100))

    reason = build_reason(
        components=components,
        facts=facts,
        config=config,
        missing_skills=missing_skills,
        matched_req_count=matched_req,
        total_req_count=total_req,
        days_old=days_old,
        listing=listing,
    )

    return {
        "score": final_score,
        "reason": reason,
        "components": components,
    }

