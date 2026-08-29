"""edgedash/verification.py — Pure verification checks for cycle outputs.

No LLM calls, no clock calls, no network, no database reads.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import statistics
from typing import Any

from edgedash.config import Config


@dataclass
class CheckResult:
    name: str
    passed: bool
    observed: Any
    threshold: Any
    message: str


@dataclass
class Verdict:
    passed: bool
    failed_checks: list[CheckResult]
    summary: str
    all_results: list[CheckResult] = field(default_factory=list)


def check_score_spread(scores: list[float], config: Config) -> CheckResult:
    """FAILS if max - min < min_score_spread, or if stdev is below min_score_stdev.
    Passes trivially if fewer than 5 scores.
    Catches score inflation / clustering failure mode.
    """
    name = "score_spread"
    min_spread = float(getattr(config, "min_score_spread", 10.0))
    min_stdev = float(getattr(config, "min_score_stdev", 5.0))
    threshold_desc = {"min_score_spread": min_spread, "min_score_stdev": min_stdev}

    if len(scores) < 5:
        return CheckResult(
            name=name,
            passed=True,
            observed={"count": len(scores)},
            threshold={"min_count": 5},
            message=f"Fewer than 5 scores ({len(scores)}), score spread check passed trivially.",
        )

    score_range = max(scores) - min(scores)
    score_stdev = statistics.stdev(scores)
    observed_desc = {"range": round(score_range, 2), "stdev": round(score_stdev, 2)}

    if score_range < min_spread:
        return CheckResult(
            name=name,
            passed=False,
            observed=observed_desc,
            threshold=threshold_desc,
            message=f"Score spread ({score_range:.2f}) is below minimum threshold ({min_spread}).",
        )

    if score_stdev < min_stdev:
        return CheckResult(
            name=name,
            passed=False,
            observed=observed_desc,
            threshold=threshold_desc,
            message=f"Score standard deviation ({score_stdev:.2f}) is below minimum threshold ({min_stdev}).",
        )

    return CheckResult(
        name=name,
        passed=True,
        observed=observed_desc,
        threshold=threshold_desc,
        message=f"Score spread check passed (range={score_range:.2f}, stdev={score_stdev:.2f}).",
    )


def check_extraction_sanity(facts_list: list[dict[str, Any]], config: Config) -> CheckResult:
    """FAILS if > max_empty_extraction_pct of listings have an empty required_skills list,
    or if any listing has > max_skills_per_listing.
    Catches broken extractor and model returning whole sentences as skills.
    """
    name = "extraction_sanity"
    max_empty_pct = float(getattr(config, "max_empty_extraction_pct", 20.0))
    max_skills_limit = int(getattr(config, "max_skills_per_listing", 20))
    threshold_desc = {
        "max_empty_extraction_pct": max_empty_pct,
        "max_skills_per_listing": max_skills_limit,
    }

    if not facts_list:
        return CheckResult(
            name=name,
            passed=True,
            observed={"count": 0, "empty_pct": 0.0, "max_skills": 0},
            threshold=threshold_desc,
            message="No extractions to verify.",
        )

    empty_count = 0
    max_skills_found = 0

    for item in facts_list:
        skills = item.get("required_skills", []) if isinstance(item, dict) else getattr(item, "required_skills", [])
        if not skills:
            empty_count += 1
        else:
            max_skills_found = max(max_skills_found, len(skills))

    empty_pct = (empty_count / len(facts_list)) * 100.0
    observed_desc = {
        "total_listings": len(facts_list),
        "empty_pct": round(empty_pct, 2),
        "max_skills": max_skills_found,
    }

    if empty_pct > max_empty_pct:
        return CheckResult(
            name=name,
            passed=False,
            observed=observed_desc,
            threshold=threshold_desc,
            message=f"Empty skills extraction rate ({empty_pct:.1f}%) exceeded maximum threshold ({max_empty_pct}%).",
        )

    if max_skills_found > max_skills_limit:
        return CheckResult(
            name=name,
            passed=False,
            observed=observed_desc,
            threshold=threshold_desc,
            message=f"Listing found with {max_skills_found} skills, exceeding maximum threshold ({max_skills_limit}).",
        )

    return CheckResult(
        name=name,
        passed=True,
        observed=observed_desc,
        threshold=threshold_desc,
        message=f"Extraction sanity check passed (empty_pct={empty_pct:.1f}%, max_skills={max_skills_found}).",
    )


def check_gap_sample_size(gaps: list[dict[str, Any]], config: Config) -> CheckResult:
    """FAILS if the top-ranked gap was computed from fewer than min_gap_sample listings.
    Catches ranking a rumour.
    """
    name = "gap_sample_size"
    min_sample = int(getattr(config, "min_gap_sample", 3))
    threshold_desc = {"min_gap_sample": min_sample}

    if not gaps:
        return CheckResult(
            name=name,
            passed=True,
            observed={"top_gap_sample": 0},
            threshold=threshold_desc,
            message="No skill gaps to check.",
        )

    top_gap = gaps[0]
    if isinstance(top_gap, dict):
        sample_size = top_gap.get("listings_blocked")
        if sample_size is None:
            sample_size = top_gap.get("sample_size")
        if sample_size is None:
            sample_size = len(top_gap.get("example_ids", []))
        top_skill = top_gap.get("skill", "unknown")
    else:
        sample_size = getattr(top_gap, "listings_blocked", getattr(top_gap, "sample_size", 0))
        top_skill = getattr(top_gap, "skill", "unknown")

    sample_size = int(sample_size or 0)
    observed_desc = {"top_gap": top_skill, "sample_size": sample_size}

    if sample_size < min_sample:
        return CheckResult(
            name=name,
            passed=False,
            observed=observed_desc,
            threshold=threshold_desc,
            message=f"Top-ranked gap '{top_skill}' was computed from only {sample_size} listing(s) (minimum required: {min_sample}).",
        )

    return CheckResult(
        name=name,
        passed=True,
        observed=observed_desc,
        threshold=threshold_desc,
        message=f"Gap sample size check passed (top gap '{top_skill}' computed from {sample_size} listings).",
    )


def check_freshness(
    latest_fetch_at: str | datetime | None, config: Config, now: datetime
) -> CheckResult:
    """FAILS if the newest listing is older than max_data_age_days.
    `now` is a PARAMETER, never datetime.now() inside the function.
    Catches stale data ingestion.
    """
    name = "freshness"
    max_days = float(getattr(config, "max_data_age_days", 3))
    threshold_desc = {"max_data_age_days": max_days}

    if latest_fetch_at is None:
        return CheckResult(
            name=name,
            passed=False,
            observed={"latest_fetch_at": None, "age_days": None},
            threshold=threshold_desc,
            message="No fetch timestamp provided.",
        )

    if isinstance(latest_fetch_at, str):
        cleaned_str = latest_fetch_at.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(cleaned_str)
        except ValueError:
            return CheckResult(
                name=name,
                passed=False,
                observed={"latest_fetch_at": latest_fetch_at},
                threshold=threshold_desc,
                message=f"Invalid timestamp format: '{latest_fetch_at}'.",
            )
    else:
        dt = latest_fetch_at

    if now.tzinfo is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif now.tzinfo is None and dt.tzinfo is not None:
        now = now.replace(tzinfo=timezone.utc)

    age = now - dt
    age_days = age.total_seconds() / 86400.0
    observed_desc = {"latest_fetch_at": str(latest_fetch_at), "age_days": round(age_days, 2)}

    if age_days > max_days:
        return CheckResult(
            name=name,
            passed=False,
            observed=observed_desc,
            threshold=threshold_desc,
            message=f"Newest listing is {age_days:.1f} days old, exceeding max allowed data age of {max_days} days.",
        )

    return CheckResult(
        name=name,
        passed=True,
        observed=observed_desc,
        threshold=threshold_desc,
        message=f"Freshness check passed (data age: {age_days:.1f} days).",
    )


def run_all_checks(
    config: Config,
    scores: list[float] | None = None,
    facts_list: list[dict[str, Any]] | None = None,
    gaps: list[dict[str, Any]] | None = None,
    latest_fetch_at: str | datetime | None = None,
    now: datetime | None = None,
) -> Verdict:
    """Runs every provided check, collects results, and returns a Verdict passing only if all pass."""
    results: list[CheckResult] = []

    if scores is not None:
        results.append(check_score_spread(scores, config))

    if facts_list is not None:
        results.append(check_extraction_sanity(facts_list, config))

    if gaps is not None:
        results.append(check_gap_sample_size(gaps, config))

    if latest_fetch_at is not None and now is not None:
        results.append(check_freshness(latest_fetch_at, config, now))

    failed = [r for r in results if not r.passed]
    passed_all = len(failed) == 0

    if passed_all:
        summary = f"All {len(results)} verification checks passed."
    else:
        summary = f"{len(failed)} of {len(results)} verification checks failed: {', '.join(r.name for r in failed)}."

    return Verdict(
        passed=passed_all,
        failed_checks=failed,
        summary=summary,
        all_results=results,
    )
