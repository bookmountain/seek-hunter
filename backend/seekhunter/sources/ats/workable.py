"""Workable's public careers-page API (what apply.workable.com/{account} itself calls):
- list:   POST https://apply.workable.com/api/v3/accounts/{token}/jobs
          body {"query":"","location":[],"department":[],"worktype":[],"remote":[]}, paged with
          `"token": <nextPage>`; no descriptions.
- detail: GET  https://apply.workable.com/api/v2/accounts/{token}/jobs/{shortcode}
          (description / requirements / benefits HTML)."""

from dataclasses import replace

from seekhunter.domain import JobData, normalize_work_type, seek_location
from seekhunter.sources.ats.base import Company, get_json, parse_iso, radar_job, require_token

BASE = "https://apply.workable.com"
MAX_PAGES = 10
_TYPES = {"full": "full_time", "part": "part_time", "contract": "contract", "temporary": "contract"}


def _place(loc: dict) -> str:
    city, region, country = loc.get("city") or "", loc.get("region") or "", loc.get("country") or ""
    if (loc.get("countryCode") or "").upper() == "AU":
        text = seek_location(", ".join(p for p in (city, region) if p))
        return f"{text}, Australia" if text else "Australia"
    return ", ".join(p for p in (city, region, country) if p)


def _location(job: dict) -> str:
    locs = [job.get("location") or {}, *(job.get("locations") or [])]
    au = next((x for x in locs if (x.get("countryCode") or "").upper() == "AU"), None)
    return _place(au or locs[0])


def parse_results(payload: dict, company: Company, token: str) -> list[JobData]:
    out = []
    for j in payload.get("results") or []:
        code = j.get("shortcode")
        if not code:
            continue
        out.append(radar_job(
            ats="workable", ext=code, title=j.get("title") or "", company=company,
            location=_location(j), url=f"{BASE}/{token}/j/{code}/",
            work_type=_TYPES.get(j.get("type") or "", normalize_work_type(j.get("type"))),
            listed_at=parse_iso(j.get("published")),
        ))
    return out


def parse_detail(payload: dict) -> str:
    parts = []
    for key, heading in (("description", None), ("requirements", "Requirements"), ("benefits", "Benefits")):
        body = payload.get(key) or ""
        if body:
            parts.append(f"<h3>{heading}</h3>{body}" if heading else body)
    return "\n".join(parts)


class WorkableClient:
    ats = "workable"

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def list_jobs(self, company: Company) -> list[JobData]:
        token = require_token(company, self.ats)
        body: dict = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
        jobs: list[JobData] = []
        for _ in range(MAX_PAGES):
            resp = self.client.post(f"{BASE}/api/v3/accounts/{token}/jobs", json=body)
            payload = get_json(resp, f"workable {token}")
            jobs.extend(parse_results(payload, company, token))
            if not payload.get("nextPage"):
                break
            body = {**body, "token": payload["nextPage"]}
        return jobs

    def details(self, job: JobData) -> JobData:
        if job.description_html:
            return job
        token, code = _token_and_code(job)
        payload = get_json(self.client.get(f"{BASE}/api/v2/accounts/{token}/jobs/{code}"),
                           f"workable {token}/{code}")
        return replace(job, description_html=parse_detail(payload) or job.description_html)


def _token_and_code(job: JobData) -> tuple[str, str]:
    # url: https://apply.workable.com/{token}/j/{shortcode}/
    parts = job.url.removeprefix(BASE).strip("/").split("/")
    return parts[0], job.external_id.removeprefix("workable:")
