"""Lever postings API: https://api.lever.co/v0/postings/{token}?mode=json (public, no key)."""

from seekhunter.domain import JobData, normalize_work_type
from seekhunter.sources.ats.base import (
    Company,
    from_millis,
    get_json,
    is_australian,
    radar_job,
    require_token,
)

API = "https://api.lever.co/v0/postings"
_INTERVALS = {"per-hour-wage": "hour", "per-day-wage": "day", "per-week-salary": "week",
              "per-month-salary": "month", "per-year-salary": "year"}


def _location(job: dict) -> str:
    cats = job.get("categories") or {}
    loc = (cats.get("location") or "").strip()
    if not is_australian(loc):
        loc = next((x for x in cats.get("allLocations") or [] if is_australian(x)), loc)
    if (job.get("country") or "").upper() == "AU" and not is_australian(loc):
        loc = f"{loc}, Australia" if loc else "Australia"
    return loc


def _description(job: dict) -> str:
    parts = [job.get("description") or ""]
    for item in job.get("lists") or []:
        parts.append(f"<h3>{item.get('text') or ''}</h3><ul>{item.get('content') or ''}</ul>")
    parts.append(job.get("additional") or "")
    return "\n".join(p for p in parts if p)


def _salary(job: dict) -> str | None:
    sr = job.get("salaryRange") or {}
    low, high = sr.get("min"), sr.get("max")
    if not low and not high:
        return None
    amount = f"${low:,.0f} – ${high:,.0f}" if low and high else f"${(low or high):,.0f}"
    unit = _INTERVALS.get(sr.get("interval") or "")
    return f"{amount} per {unit}" if unit else amount


def parse_postings(payload: list, company: Company) -> list[JobData]:
    out = []
    for j in payload or []:
        if not j.get("id"):
            continue
        out.append(radar_job(
            ats="lever", ext=str(j["id"]), title=j.get("text") or "", company=company,
            location=_location(j), url=j.get("hostedUrl") or "",
            work_type=normalize_work_type((j.get("categories") or {}).get("commitment")),
            listed_at=from_millis(j.get("createdAt")), description_html=_description(j),
            salary_label=_salary(j),
        ))
    return out


class LeverClient:
    ats = "lever"

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def list_jobs(self, company: Company) -> list[JobData]:
        token = require_token(company, self.ats)
        payload = get_json(self.client.get(f"{API}/{token}", params={"mode": "json"}), f"lever {token}")
        if not isinstance(payload, list):
            return []
        return parse_postings(payload, company)

    def details(self, job: JobData) -> JobData:
        return job
