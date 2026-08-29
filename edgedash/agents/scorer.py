import statistics
from typing import Any

from edgedash import storage
from edgedash.agents.base import AgentResult
from edgedash.agents.extractor import extract
from edgedash.config import Config
from edgedash.scoring import score_listing


class Scorer:
    name: str = "Scorer"

    def run(
        self,
        config: Config,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
        widen_distribution: bool = False,
        **kwargs: Any,
    ) -> AgentResult:
        db_path = config.db_path
        if stop_conditions and "max_items" in stop_conditions:
            batch_size = int(stop_conditions["max_items"])
        else:
            batch_size = getattr(config, "score_batch_size", 50)

        unscored = storage.get_unscored_listings(db_path, limit=batch_size)

        scores: list[int] = []
        failed_count = 0

        for listing in unscored:
            try:
                facts = extract(listing, config=config)
                score_res = score_listing(listing, facts, config, widen_distribution=widen_distribution)


                fit_score = int(score_res["score"])
                fit_reason = str(score_res["reason"])

                listing_id = str(listing.get("id") or "")
                if listing_id:
                    storage.update_listing_score(
                        db_path=db_path,
                        listing_id=listing_id,
                        fit_score=fit_score,
                        fit_reason=fit_reason,
                    )
                scores.append(fit_score)
            except Exception as err:
                failed_count += 1
                listing_title = listing.get("title", "Unknown")
                print(f"[Scorer] WARNING: Failed to score listing '{listing_title}': {err}")
                continue

        scored_count = len(scores)

        if scored_count > 0:
            min_score = min(scores)
            max_score = max(scores)
            mean_score = int(round(statistics.mean(scores)))
            spread = max_score - min_score

            if spread < 10 and scored_count > 1:
                spread_flag = "spread SUSPECT"
                status_str = "suspect"
            else:
                spread_flag = "spread OK"
                status_str = "ok"

            notes_str = (
                f"scored {scored_count} · range {min_score}-{max_score} · "
                f"mean {mean_score} · {failed_count} failed · {spread_flag}"
            )
        else:
            status_str = "ok"
            notes_str = f"scored 0 · {failed_count} failed"

        return AgentResult(
            agent=self.name,
            status=status_str,
            records_touched=scored_count,
            notes=notes_str,
        )


def main() -> None:
    import argparse
    from edgedash.config import load_config

    parser = argparse.ArgumentParser(description="Run Scorer agent")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of listings to score")
    args = parser.parse_args()

    cfg = load_config()
    if args.limit is not None:
        cfg.score_batch_size = args.limit

    storage.init_db(cfg.db_path)
    scorer = Scorer()
    res = scorer.run(cfg)
    print(f"Scorer result: status={res.status}, records_touched={res.records_touched}, notes='{res.notes}'")


if __name__ == "__main__":
    main()

