import os
from typing import Any

from edgedash.config import Config
from edgedash.sources.base import get_json, register

API_URL = "https://api.apify.com/v2/acts/apify~job-scraper/run-sync-get-dataset-items"


@register("apify")
class ApifySource:
    name: str = "apify"

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        external_id = (
            item.get("id")
            or item.get("jobId")
            or item.get("external_id")
        )
        title = (
            item.get("title")
            or item.get("positionName")
            or item.get("jobTitle")
            or item.get("role")
        )
        company = (
            item.get("companyName")
            or item.get("company")
            or item.get("employer")
            or item.get("organization")
        )
        location = (
            item.get("location")
            or item.get("jobLocation")
            or item.get("city")
        )
        url = (
            item.get("url")
            or item.get("jobUrl")
            or item.get("link")
            or item.get("applyUrl")
        )
        description = (
            item.get("description")
            or item.get("jobDescription")
            or item.get("text")
            or item.get("details")
        )
        posted_at = (
            item.get("postedAt")
            or item.get("posted_at")
            or item.get("publishedAt")
            or item.get("createdAt")
            or item.get("date")
        )

        return {
            "source": self.name,
            "external_id": str(external_id) if external_id is not None else None,
            "title": str(title) if title is not None else None,
            "company": str(company) if company is not None else None,
            "location": str(location) if location is not None else None,
            "url": str(url) if url is not None else None,
            "description": str(description) if description is not None else None,
            "posted_at": str(posted_at) if posted_at is not None else None,
            "raw": item,
        }

    def fetch(self, config: Config) -> list[dict[str, Any]]:
        token = os.getenv("APIFY_TOKEN")
        if not token:
            print("apify: no APIFY_TOKEN, skipping")
            return []

        params = {
            "token": token,
            "position": config.target_role,
            "location": config.target_city,
            "limit": 100,
            "maxItems": 100,
        }

        res = get_json(API_URL, params=params)

        if isinstance(res, list):
            items = res
        elif isinstance(res, dict):
            items = res.get("items") or res.get("data") or []
        else:
            items = []

        # Cap results at 100 per run
        items = items[:100]

        print(f"[{self.name}] Retrieved {len(items)} listings from Apify.")
        return [self._normalize_item(item) for item in items]
