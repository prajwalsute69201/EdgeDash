from datetime import datetime, timezone
from typing import Any
from edgedash.config import Config
from edgedash.sources.base import get_json, register

API_URL = "https://www.arbeitnow.com/api/job-board-api"


@register("arbeitnow")
class ArbeitnowSource:
    name: str = "arbeitnow"

    def _matches_keywords(self, item: dict[str, Any], keywords: list[str]) -> bool:
        if not keywords:
            return True

        title = str(item.get("title") or "").lower()
        description = str(item.get("description") or "").lower()
        tags = [str(t).lower() for t in item.get("tags") or []]

        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in title or kw_lower in description or any(kw_lower in tag for tag in tags):
                return True
        return False

    def _matches_location(self, item: dict[str, Any], target_city: str) -> bool:
        if not target_city:
            return True

        location_str = str(item.get("location") or "").lower()
        is_remote = bool(item.get("remote"))
        city_lower = target_city.lower()

        return city_lower in location_str or is_remote or "remote" in location_str

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        slug = item.get("slug") or item.get("id")
        external_id = str(slug) if slug else None

        title = item.get("title") or None
        company = item.get("company_name") or None
        location = item.get("location") or None
        url = item.get("url") or None
        description = item.get("description") or None

        posted_at = None
        created_at = item.get("created_at")
        if created_at is not None:
            try:
                posted_at = datetime.fromtimestamp(int(created_at), timezone.utc).isoformat()
            except (ValueError, TypeError, OverflowError):
                posted_at = None

        return {
            "source": self.name,
            "external_id": external_id,
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "description": description,
            "posted_at": posted_at,
            "raw": item,
        }

    def fetch(self, config: Config) -> list[dict[str, Any]]:
        raw_items: list[dict[str, Any]] = []

        # Fetch up to 5 pages
        for page in range(1, 6):
            data = get_json(API_URL, params={"page": page})
            page_data = data.get("data") or []
            if not page_data:
                break

            raw_items.extend(page_data)

            # Stop paging if no items on current page match any config keywords
            if not any(self._matches_keywords(item, config.keywords) for item in page_data):
                break

        print(f"[{self.name}] Retrieved {len(raw_items)} raw job listings across page iterations.")

        # Filter against keywords and location
        keyword_matched = [item for item in raw_items if self._matches_keywords(item, config.keywords)]
        strict_matched = [
            item for item in keyword_matched if self._matches_location(item, config.target_city)
        ]

        if len(strict_matched) < 5:
            print(
                f"[{self.name}] Location filter produced <5 results ({len(strict_matched)}). "
                f"Relaxing location filter to surface remote/nearby roles."
            )
            final_items = keyword_matched
        else:
            final_items = strict_matched

        print(f"[{self.name}] {len(final_items)} job listings survived filtering.")
        return [self._normalize_item(item) for item in final_items]
