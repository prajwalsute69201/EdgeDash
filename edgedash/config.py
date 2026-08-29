import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


@dataclass
class Config:
    target_role: str = "Data Analyst"
    target_city: str = "Dubai"
    keywords: list[str] = field(default_factory=list)
    my_skills: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    experience_years: int = 0
    db_path: str = "edgedash.db"
    min_fit_score: int = 60
    sources: list[str] = field(default_factory=lambda: ["arbeitnow"])
    use_mock_fetcher: bool = False
    llm_provider: str = "gemini"
    llm_model: str = "gemini-3.6-flash"
    score_batch_size: int = 50
    weight_skill_match: float = 0.45
    weight_seniority_fit: float = 0.25
    weight_location_fit: float = 0.15
    weight_recency: float = 0.15
    skill_aliases: dict[str, str] = field(default_factory=dict)
    fetch_interval_hours: float = 6.0
    max_fetch_pages: int = 5
    max_fetch_listings: int = 100
    max_score_seconds: int = 60
    max_analyse_seconds: int = 30
    min_score_spread: float = 10.0
    min_score_stdev: float = 5.0
    max_empty_extraction_pct: float = 20.0
    max_skills_per_listing: int = 20
    min_gap_sample: int = 3
    max_data_age_days: int = 3
    daily_ask_cap: int = 200


def _parse_simple_yaml(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- ") and current_key:
                val = stripped[2:].strip().strip('"\'')
                data.setdefault(current_key, []).append(val)
            elif ":" in stripped:
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip().strip('"\'')
                if val:
                    data[key] = val
                    current_key = None
                else:
                    data[key] = []
                    current_key = key
    return data


def _parse_experience_years(val: Any) -> int:
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        numbers = [int(n) for n in re.findall(r"\d+", val)]
        if numbers:
            return max(numbers)
    return 0


def _parse_str_or_first(val: Any, default: str) -> str:
    if isinstance(val, list) and val:
        return str(val[0])
    if isinstance(val, str) and val:
        return val
    return default


try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore


def load_config(config_path: str | Path = "config.yaml") -> Config:
    if load_dotenv is not None:
        load_dotenv()

    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file absent: {path.absolute()}. Please ensure config.yaml exists."
        )

    data: dict[str, Any] = {}
    if yaml is not None:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = _parse_simple_yaml(path)

    raw_role = data.get("target_role")
    raw_city = data.get("target_city")

    raw_sources = data.get("sources")
    if raw_sources is None:
        sources = ["arbeitnow"]
    elif isinstance(raw_sources, list):
        sources = [str(s) for s in raw_sources]
    else:
        sources = [str(raw_sources)]

    raw_mock = data.get("use_mock_fetcher")
    if isinstance(raw_mock, bool):
        use_mock_fetcher = raw_mock
    elif isinstance(raw_mock, str):
        use_mock_fetcher = raw_mock.lower() in ("true", "1", "yes")
    else:
        use_mock_fetcher = False

    llm_provider = str(data.get("llm_provider") or "gemini")
    llm_model = str(data.get("llm_model") or "gemini-3.6-flash")

    my_skills = list(data.get("my_skills") or data.get("skills") or [])

    return Config(
        target_role=_parse_str_or_first(raw_role, "Data Analyst"),
        target_city=_parse_str_or_first(raw_city, "Dubai"),
        keywords=list(data.get("keywords") or []),
        my_skills=my_skills,
        skills=my_skills,
        experience_years=_parse_experience_years(data.get("experience_years")),
        db_path=str(data.get("db_path") or "edgedash.db"),
        min_fit_score=int(data.get("min_fit_score") or 60),
        sources=sources,
        use_mock_fetcher=use_mock_fetcher,
        llm_provider=llm_provider,
        llm_model=llm_model,
        score_batch_size=int(data.get("score_batch_size") or 50),
        weight_skill_match=float(data.get("weight_skill_match", 0.45)),
        weight_seniority_fit=float(data.get("weight_seniority_fit", 0.25)),
        weight_location_fit=float(data.get("weight_location_fit", 0.15)),
        weight_recency=float(data.get("weight_recency", 0.15)),
        skill_aliases=dict(data.get("skill_aliases") or {}),
        fetch_interval_hours=float(data.get("fetch_interval_hours", 6.0)),
        max_fetch_pages=int(data.get("max_fetch_pages", 5)),
        max_fetch_listings=int(data.get("max_fetch_listings", 100)),
        max_score_seconds=int(data.get("max_score_seconds", 60)),
        max_analyse_seconds=int(data.get("max_analyse_seconds", 30)),
        min_score_spread=float(data.get("min_score_spread", 10.0)),
        min_score_stdev=float(data.get("min_score_stdev", 5.0)),
        max_empty_extraction_pct=float(data.get("max_empty_extraction_pct", 20.0)),
        max_skills_per_listing=int(data.get("max_skills_per_listing", 20)),
        min_gap_sample=int(data.get("min_gap_sample", 3)),
        max_data_age_days=int(data.get("max_data_age_days", 3)),
        daily_ask_cap=int(data.get("daily_ask_cap", 200)),
    )



