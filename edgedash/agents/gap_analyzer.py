import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from edgedash import storage
from edgedash.agents.base import AgentResult
from edgedash.agents.extractor import compute_description_hash
from edgedash.config import Config
from edgedash.skills import canonical


class GapAnalyzer:
    name: str = "GapAnalyzer"

    def run(
        self,
        config: Config,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        db_path = config.db_path
        aliases = getattr(config, "skill_aliases", {})

        # Candidate skills canonicalised
        raw_my_skills = getattr(config, "skills", None) or getattr(config, "my_skills", [])
        candidate_skills = {
            canonical(s, aliases) for s in raw_my_skills if isinstance(s, str) and s.strip()
        }

        # Read every scored listing from storage
        scored_listings = storage.get_scored_listings(db_path)
        listings_analysed = len(scored_listings)

        if not scored_listings:
            return AgentResult(
                agent=self.name,
                status="ok",
                records_touched=0,
                notes="0 gaps · 0 listings analysed",
            )

        skill_listings: dict[str, list[dict[str, Any]]] = defaultdict(list)
        nice_to_have_counts: dict[str, int] = defaultdict(int)

        for listing in scored_listings:
            description = str(listing.get("description") or "")
            desc_hash = compute_description_hash(description)
            facts = storage.get_extraction(db_path, desc_hash)
            if not facts:
                continue

            # Required skills gap tracking
            req_skills = facts.get("required_skills", [])
            seen_req_in_listing: set[str] = set()

            for raw_skill in req_skills:
                canon_skill = canonical(raw_skill, aliases)
                if canon_skill and canon_skill not in candidate_skills:
                    if canon_skill not in seen_req_in_listing:
                        seen_req_in_listing.add(canon_skill)
                        skill_listings[canon_skill].append(listing)

            # Nice to have tracking (tracked separately, never mixed into required count)
            nice_skills = facts.get("nice_to_have", [])
            seen_nice_in_listing: set[str] = set()

            for raw_skill in nice_skills:
                canon_skill = canonical(raw_skill, aliases)
                if (
                    canon_skill
                    and canon_skill not in candidate_skills
                    and canon_skill not in seen_req_in_listing
                ):
                    if canon_skill not in seen_nice_in_listing:
                        seen_nice_in_listing.add(canon_skill)
                        nice_to_have_counts[canon_skill] += 1

        all_gap_metrics: list[dict[str, Any]] = []

        for skill, listings in skill_listings.items():
            # Deduplicate by listing ID if needed
            unique_dict: dict[str, dict[str, Any]] = {}
            for l in listings:
                lid = str(l.get("id") or "")
                if lid and lid not in unique_dict:
                    unique_dict[lid] = l

            unique_listings = list(unique_dict.values())
            sorted_listings = sorted(
                unique_listings, key=lambda l: int(l.get("fit_score") or 0), reverse=True
            )

            scores = [int(l.get("fit_score") or 0) for l in sorted_listings]
            blocked_count = len(scores)

            # Opportunity cost calculation per Rule 24: sum(fit_score / 100.0)
            opportunity_cost = sum(s / 100.0 for s in scores)
            mean_score = sum(scores) / blocked_count if blocked_count > 0 else 0.0
            top_score = max(scores) if scores else 0
            example_ids = [str(l.get("id")) for l in sorted_listings[:5]]

            # Rule 27: Flag < 3 listings as low confidence
            confidence = "low confidence" if blocked_count < 3 else "normal"

            all_gap_metrics.append(
                {
                    "skill": skill,
                    "listings_blocked": blocked_count,
                    "opportunity_cost": round(opportunity_cost, 2),
                    "mean_score": round(mean_score, 1),
                    "top_score": top_score,
                    "example_ids": example_ids,
                    "also_nice_to_have": nice_to_have_counts.get(skill, 0),
                    "confidence": confidence,
                }
            )

        # Rank by opportunity_cost descending
        all_gap_metrics.sort(key=lambda g: g["opportunity_cost"], reverse=True)
        top_gaps = all_gap_metrics[:10]

        # Rule 25: Save timestamped snapshot to storage
        run_id = str(uuid.uuid4())[:8]
        computed_at = datetime.now(timezone.utc).isoformat()
        storage.save_gap_snapshot(
            db_path=db_path,
            run_id=run_id,
            computed_at=computed_at,
            gaps=top_gaps,
        )

        total_gaps_found = len(all_gap_metrics)

        if top_gaps:
            top_item = top_gaps[0]
            top_skill = top_item["skill"]
            top_count = top_item["listings_blocked"]
            top_cost = top_item["opportunity_cost"]
            notes_str = (
                f"{total_gaps_found} gaps · top: {top_skill} "
                f"({top_count} listings, cost {top_cost:.1f}) · {listings_analysed} listings analysed"
            )
        else:
            notes_str = f"0 gaps · {listings_analysed} listings analysed"

        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=total_gaps_found,
            notes=notes_str,
        )
