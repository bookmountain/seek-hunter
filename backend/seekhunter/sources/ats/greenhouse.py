"""Greenhouse job board API: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
(public, no key; `content` is the ad HTML, entity-escaped)."""

import html

from seekhunter.domain import JobData
from seekhunter.sources.ats.base import Company, get_json, is_australian, parse_iso, radar_job, require_token

API = "https://boards-api.greenhouse.io/v1/boards"


def _location(job: dict) -> str:
    loc = ((job.get("location") or {}).get("name") or "").strip()
    if is_australian(loc):
        return loc
    for office in job.get("offices") or []:
        name = (office.get("location") or office.get("name") or "").strip()
        if is_australian(name):
            return name
    return loc


def parse_jobs(payload: dict, company: Company) -> list[JobData]:
    return [
        radar_job(
            ats="greenhouse", ext=str(j["id"]), title=j.get("title") or "", company=company,
            location=_location(j), url=j.get("absolute_url") or "",
            listed_at=parse_iso(j.get("first_published") or j.get("updated_at")),
            description_html=html.unescape(j.get("content") or ""),
        )
        for j in payload.get("jobs") or []
        if j.get("id") is not None
    ]


class GreenhouseClient:
    ats = "greenhouse"

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def list_jobs(self, company: Company) -> list[JobData]:
        token = require_token(company, self.ats)
        resp = self.client.get(f"{API}/{token}/jobs", params={"content": "true"})
        return parse_jobs(get_json(resp, f"greenhouse {token}"), company)

    def details(self, job: JobData) -> JobData:
        return job
