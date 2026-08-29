from datetime import datetime, timezone
from typing import Any
from edgedash.agents.base import AgentResult
from edgedash import storage
from edgedash.config import Config


class MockFetcher:
    name: str = "Fetcher"

    def _generate_mock_listings(self, config: Config) -> list[dict[str, Any]]:
        now_str = datetime.now(timezone.utc).isoformat()
        role = config.target_role
        city = config.target_city

        # 4 static listings (fixed URLs and sources) to prove deduplication on repeated runs
        static_listings = [
            {
                "url": f"https://careers.techcorp.ae/jobs/{city.lower()}/sr-data-analyst-101",
                "source": "LinkedIn",
                "title": f"Senior {role}",
                "company": "TechCorp Middle East",
                "location": city,
                "description": f"Looking for a Senior {role} with 3+ years in SQL, Python, Pandas, and Tableau to build executive dashboards.",
                "posted_at": "2026-08-20T10:00:00Z",
                "fetched_at": now_str,
            },
            {
                "url": f"https://jobs.fintechgulf.com/roles/{city.lower()}/bi-analyst-102",
                "source": "Indeed",
                "title": f"Business Intelligence {role}",
                "company": "FinTech Gulf Solutions",
                "location": city,
                "description": f"Seeking a BI {role} proficient in Power BI, SQL, Data Modeling, and Excel reporting for financial metrics.",
                "posted_at": "2026-08-21T09:30:00Z",
                "fetched_at": now_str,
            },
            {
                "url": f"https://bayt.com/en/job/{city.lower()}/product-data-analyst-103",
                "source": "Bayt",
                "title": f"Product {role}",
                "company": "Careem Logistics",
                "location": city,
                "description": f"Join our product team as a Product {role}. Core skills required: Python, SQL, A/B Testing, and Matplotlib.",
                "posted_at": "2026-08-22T14:15:00Z",
                "fetched_at": now_str,
            },
            {
                "url": f"https://gulftalent.com/jobs/{city.lower()}/reporting-analyst-104",
                "source": "GulfTalent",
                "title": f"Reporting & MIS {role}",
                "company": "Al Futtaim Group",
                "location": city,
                "description": f"Hiring an MIS {role} to analyze sales data using Google Sheets, SQL, Tableau, and Jupyter Notebooks.",
                "posted_at": "2026-08-23T08:00:00Z",
                "fetched_at": now_str,
            },
        ]

        # 8 dynamic listings generated per fetch cycle run
        run_tag = datetime.now(timezone.utc).strftime("%H%M%S")
        companies = [
            "Emirates NBD",
            "Majid Al Futtaim",
            "Noon.com",
            "Emaar Properties",
            "Chalhoub Group",
            "DP World",
            "First Abu Dhabi Bank",
            "Talabat UAE",
        ]
        seniorities = [
            "Junior",
            "Associate",
            "Lead",
            "Principal",
            "Staff",
            "Mid-Level",
            "Quantitative",
            "Operations",
        ]

        dynamic_listings = []
        for idx, (company, seniority) in enumerate(zip(companies, seniorities), start=1):
            dynamic_listings.append(
                {
                    "url": f"https://jobs.example.com/{city.lower()}/job-{idx}-{run_tag}",
                    "source": "MockPortal",
                    "title": f"{seniority} {role}",
                    "company": company,
                    "location": city,
                    "description": f"Role for {seniority} {role} at {company} in {city}. Key tech stack: Python, SQL, Seaborn, NumPy, Power BI.",
                    "posted_at": "2026-08-23T12:00:00Z",
                    "fetched_at": now_str,
                }
            )

        return static_listings + dynamic_listings

    def run(
        self,
        config: Config,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        listings = self._generate_mock_listings(config)
        new_inserted = storage.upsert_listings(config.db_path, listings)
        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=new_inserted,
            notes=f"Fetched 12 listings, {new_inserted} new inserted",
        )
