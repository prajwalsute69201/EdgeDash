from datetime import datetime, timezone
import pytest
from edgedash.config import Config
from edgedash.verification import (
    CheckResult,
    Verdict,
    check_extraction_sanity,
    check_freshness,
    check_gap_sample_size,
    check_score_spread,
    run_all_checks,
)


@pytest.fixture
def dummy_config() -> Config:
    return Config(
        min_score_spread=10.0,
        min_score_stdev=5.0,
        max_empty_extraction_pct=20.0,
        max_skills_per_listing=20,
        min_gap_sample=3,
        max_data_age_days=3.0,
    )


# --- 1. check_score_spread tests ---

def test_check_score_spread_fewer_than_5_scores(dummy_config: Config) -> None:
    scores = [70.0, 75.0, 80.0]
    result = check_score_spread(scores, dummy_config)
    assert result.passed is True
    assert result.name == "score_spread"
    assert "Fewer than 5 scores" in result.message


def test_check_score_spread_passing(dummy_config: Config) -> None:
    scores = [20.0, 40.0, 60.0, 80.0, 100.0]
    result = check_score_spread(scores, dummy_config)
    assert result.passed is True
    assert result.observed["range"] == 80.0
    assert result.observed["stdev"] > 5.0


def test_check_score_spread_failing_range(dummy_config: Config) -> None:
    scores = [70.0, 71.0, 72.0, 71.5, 70.5]  # Range is 2.0 (< 10.0)
    result = check_score_spread(scores, dummy_config)
    assert result.passed is False
    assert "below minimum threshold" in result.message


def test_check_score_spread_failing_stdev(dummy_config: Config) -> None:
    dummy_config.min_score_spread = 5.0
    dummy_config.min_score_stdev = 10.0
    scores = [70.0, 71.0, 72.0, 73.0, 76.0]  # Range is 6.0 (> 5.0), stdev is ~2.3 (< 10.0)
    result = check_score_spread(scores, dummy_config)
    assert result.passed is False
    assert "standard deviation" in result.message


# --- 2. check_extraction_sanity tests ---

def test_check_extraction_sanity_passing(dummy_config: Config) -> None:
    facts = [
        {"required_skills": ["Python", "SQL"]},
        {"required_skills": ["Tableau"]},
        {"required_skills": ["Excel", "Python"]},
        {"required_skills": ["SQL"]},
        {"required_skills": ["R", "Python"]},
    ]
    result = check_extraction_sanity(facts, dummy_config)
    assert result.passed is True
    assert result.observed["empty_pct"] == 0.0
    assert result.observed["max_skills"] == 2


def test_check_extraction_sanity_failing_empty_pct(dummy_config: Config) -> None:
    facts = [
        {"required_skills": []},
        {"required_skills": []},
        {"required_skills": ["Python"]},
        {"required_skills": ["SQL"]},
        {"required_skills": ["Tableau"]},
    ]  # 2 of 5 empty = 40.0% (> 20.0%)
    result = check_extraction_sanity(facts, dummy_config)
    assert result.passed is False
    assert "Empty skills extraction rate" in result.message


def test_check_extraction_sanity_failing_max_skills(dummy_config: Config) -> None:
    too_many_skills = [f"Skill_{i}" for i in range(25)]  # 25 > 20
    facts = [{"required_skills": too_many_skills}]
    result = check_extraction_sanity(facts, dummy_config)
    assert result.passed is False
    assert "exceeding maximum threshold" in result.message


# --- 3. check_gap_sample_size tests ---

def test_check_gap_sample_size_passing(dummy_config: Config) -> None:
    gaps = [
        {"skill": "SQL", "listings_blocked": 5},
        {"skill": "Python", "listings_blocked": 2},
    ]
    result = check_gap_sample_size(gaps, dummy_config)
    assert result.passed is True
    assert result.observed["sample_size"] == 5


def test_check_gap_sample_size_failing(dummy_config: Config) -> None:
    gaps = [
        {"skill": "COBOL", "listings_blocked": 1},  # 1 < 3
        {"skill": "SQL", "listings_blocked": 5},
    ]
    result = check_gap_sample_size(gaps, dummy_config)
    assert result.passed is False
    assert "computed from only 1 listing" in result.message


# --- 4. check_freshness tests ---

def test_check_freshness_passing(dummy_config: Config) -> None:
    now = datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc)
    latest_fetch = datetime(2026, 8, 23, 18, 0, tzinfo=timezone.utc)  # 1 day old (< 3 days)
    result = check_freshness(latest_fetch, dummy_config, now=now)
    assert result.passed is True
    assert result.observed["age_days"] == 1.0


def test_check_freshness_failing(dummy_config: Config) -> None:
    now = datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc)
    latest_fetch = "2026-08-15T18:00:00+00:00"  # 9 days old (> 3 days)
    result = check_freshness(latest_fetch, dummy_config, now=now)
    assert result.passed is False
    assert "exceeding max allowed data age" in result.message


# --- 5. run_all_checks tests ---

def test_run_all_checks_all_passing(dummy_config: Config) -> None:
    scores = [20.0, 40.0, 60.0, 80.0, 100.0]
    facts = [{"required_skills": ["Python"]}]
    gaps = [{"skill": "SQL", "listings_blocked": 5}]
    now = datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc)
    latest_fetch = datetime(2026, 8, 23, 18, 0, tzinfo=timezone.utc)

    verdict = run_all_checks(
        dummy_config,
        scores=scores,
        facts_list=facts,
        gaps=gaps,
        latest_fetch_at=latest_fetch,
        now=now,
    )
    assert verdict.passed is True
    assert len(verdict.failed_checks) == 0
    assert "All 4 verification checks passed" in verdict.summary


def test_run_all_checks_with_failures(dummy_config: Config) -> None:
    scores = [70.0, 71.0, 72.0, 71.5, 70.5]  # Score spread fails
    gaps = [{"skill": "COBOL", "listings_blocked": 1}]  # Gap sample size fails

    verdict = run_all_checks(
        dummy_config,
        scores=scores,
        gaps=gaps,
    )
    assert verdict.passed is False
    assert len(verdict.failed_checks) == 2
    failed_names = [f.name for f in verdict.failed_checks]
    assert "score_spread" in failed_names
    assert "gap_sample_size" in failed_names
