"""Ashby posting API:
https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true (public, no key)."""

import re

from seekhunter.domain import JobData, normalize_work_type, seek_location
from seekhunter.sources.ats.base import Company, get_json, is_australian, parse_iso, radar_job, require_token

API = "https://api.ashbyhq.com/posting-api/job-board"
_COUNTRY_PREFIX = re.compile(r"^[A-Z]{2}\s*-\s*")
_TYPES = {"FullTime": "full_time", "PartTime": "part_time", "Contract": "contract",
          "Temporary": "contract"}


def _place(name: str, address: dict | None) -> str:
    postal = (address or {}).get("postalAddress") or {}
    country = postal.get("addressCountry") or ""
    if country == "Australia":
        city = postal.get("addressLocality") or _COUNTRY_PREFIX.sub("", name or "").strip()
        region = postal.get("addressRegion") or ""
        loc = seek_location(f"{city}, {region}" if city and region else city or region)
        return loc if is_australian(loc) else f"{loc}, Australia" if loc else "Australia"
    return name or country


def _location(job: dict) -> str:
    primary = _place(job.get("location") or "", job.get("address"))
    if is_australian(primary):
        return primary
    for sec in job.get("secondaryLocations") or []:
        loc = _place(sec.get("location") or "", sec.get("address"))
        if is_australian(loc):
            return loc
    return primary


def parse_board(payload: dict, company: Company) -> list[JobData]:
    out = []
    for j in payload.get("jobs") or []:
        if not j.get("id") or j.get("isListed") is False:
            continue
        comp = (j.get("compensation") or {}).get("compensationTierSummary")
        out.append(radar_job(
            ats="ashby", ext=str(j["id"]), title=j.get("title") or "", company=company,
            location=_location(j), url=j.get("jobUrl") or "",
            work_type=_TYPES.get(j.get("employmentType") or "",
                                 normalize_work_type(j.get("employmentType"))),
            listed_at=parse_iso(j.get("publishedAt")), description_html=j.get("descriptionHtml") or "",
            salary_label=comp or None,
        ))
    return out


class AshbyClient:
    ats = "ashby"

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def list_jobs(self, company: Company) -> list[JobData]:
        token = require_token(company, self.ats)
        resp = self.client.get(f"{API}/{token}", params={"includeCompensation": "true"})
        return parse_board(get_json(resp, f"ashby {token}"), company)

    def details(self, job: JobData) -> JobData:
        return job
