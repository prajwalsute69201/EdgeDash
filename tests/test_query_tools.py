import os
import tempfile
import pytest
from edgedash import storage
from edgedash.query import tools


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    storage.init_db(path)

    # Seed sample listings
    storage.upsert_listings(
        path,
        [
            {
                "id": "l1",
                "title": "Senior AI Engineer",
                "company": "Acme Corp",
                "location": "Remote",
                "url": "https://example.com/1",
                "description": "Python, Docker, Kubernetes required",
                "source": "test",
                "posted_at": "2026-08-25T10:00:00Z",
                "fetched_at": "2026-08-25T10:00:00Z",
                "fit_score": 90,
                "fit_reason": "Strong Python fit",
            },
            {
                "id": "l2",
                "title": "Backend Developer",
                "company": "Beta Inc",
                "location": "New York",
                "url": "https://example.com/2",
                "description": "Go, Postgres required",
                "source": "test",
                "posted_at": "2026-08-20T10:00:00Z",
                "fetched_at": "2026-08-20T10:00:00Z",
                "fit_score": 75,
                "fit_reason": "Good match",
            },
        ],
    )

    # Seed extractions
    storage.save_extraction(
        path,
        "hash1",
        {
            "required_skills": ["python", "kubernetes"],
            "nice_to_have": ["docker"],
            "seniority": "senior",
            "years_required": 5,
            "remote_ok": True,
        },
    )

    # Seed gap snapshot
    storage.save_gap_snapshot(
        path,
        run_id="run1",
        computed_at="2026-08-25T12:00:00Z",
        gaps=[
            {
                "skill": "kubernetes",
                "opportunity_cost": 45.0,
                "listings_blocked": 1,
                "mean_score": 90.0,
                "top_score": 90,
                "example_ids": ["l1"],
                "also_nice_to_have": 0,
                "confidence": "high",
            }
        ],
    )

    yield path

    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def test_tool_decorator_registration():
    assert "companies_hiring" in tools.TOOLS
    assert "best_matches" in tools.TOOLS
    assert "top_gaps" in tools.TOOLS
    assert "gap_detail" in tools.TOOLS
    assert "trend" in tools.TOOLS
    assert "listing_count" in tools.TOOLS
    assert "skill_demand" in tools.TOOLS

    item = tools.TOOLS["companies_hiring"]
    assert item["name"] == "companies_hiring"
    assert "description" in item
    assert item["parameters"]["type"] == "object"


def test_companies_hiring_shape_and_clamping(temp_db):
    # Test valid call
    res = tools.companies_hiring(days=7, db_path=temp_db)
    assert "summary" in res
    assert "rows" in res
    assert isinstance(res["rows"], list)

    # Test lower bound clamping (days=0 -> clamped to 1)
    res_low = tools.companies_hiring(days=-5, db_path=temp_db)
    assert "1 days" in res_low["summary"]

    # Test upper bound clamping (days=100 -> clamped to 90)
    res_high = tools.companies_hiring(days=500, db_path=temp_db)
    assert "90 days" in res_high["summary"]


def test_best_matches_shape_and_clamping(temp_db):
    res = tools.best_matches(n=10, db_path=temp_db)
    assert "summary" in res
    assert "rows" in res
    assert len(res["rows"]) == 2
    assert res["rows"][0]["fit_score"] == 90

    # Lower bound clamping (n <= 0 -> 1)
    res_low = tools.best_matches(n=-2, db_path=temp_db)
    assert len(res_low["rows"]) == 1

    # Upper bound clamping (n=100 -> 25)
    assert tools._clamp_int(100, default=10, min_val=1, max_val=25) == 25
    res_high = tools.best_matches(n=100, db_path=temp_db)
    assert len(res_high["rows"]) == 2


def test_top_gaps_shape_and_clamping(temp_db):
    res = tools.top_gaps(n=5, db_path=temp_db)
    assert "summary" in res
    assert "rows" in res
    assert len(res["rows"]) == 1
    assert res["rows"][0]["skill"] == "kubernetes"

    # Clamping
    res_low = tools.top_gaps(n=0, db_path=temp_db)
    assert "1" in res_low["summary"]


def test_gap_detail_known_and_unknown_skill(temp_db):
    # Known skill
    res = tools.gap_detail(skill="Kubernetes (EKS)", db_path=temp_db)
    assert "summary" in res
    assert "rows" in res
    assert len(res["rows"]) == 1
    assert res["rows"][0]["title"] == "Senior AI Engineer"

    # Unknown skill (should return empty rows without raising)
    res_unknown = tools.gap_detail(skill="nonexistent_skill_xyz", db_path=temp_db)
    assert res_unknown["rows"] == []
    assert "No data found" in res_unknown["summary"]


def test_trend_shape_and_clamping(temp_db):
    res = tools.trend(weeks=3, db_path=temp_db)
    assert "summary" in res
    assert "rows" in res
    assert len(res["rows"]) == 1
    assert res["rows"][0]["skill"] == "kubernetes"

    # Clamping
    res_low = tools.trend(weeks=-1, db_path=temp_db)
    assert "1 weeks" in res_low["summary"]

    res_high = tools.trend(weeks=50, db_path=temp_db)
    assert "12 weeks" in res_high["summary"]


def test_listing_count_shape(temp_db):
    res = tools.listing_count(db_path=temp_db)
    assert "summary" in res
    assert "rows" in res
    assert len(res["rows"]) == 1
    row = res["rows"][0]
    assert row["total_listings"] == 2
    assert row["scored_listings"] == 2
    assert row["unscored_listings"] == 0


def test_skill_demand_known_and_unknown_skill(temp_db):
    # Known skill
    res = tools.skill_demand(skill="python", db_path=temp_db)
    assert "summary" in res
    assert len(res["rows"]) == 1
    assert res["rows"][0]["required_count"] == 1

    # Unknown skill (should return empty without raising)
    res_unknown = tools.skill_demand(skill="cobol", db_path=temp_db)
    assert res_unknown["rows"] == []
    assert "No data found" in res_unknown["summary"]
