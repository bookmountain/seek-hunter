"""SmartRecruiters Posting API (public, no key):
- list:   GET https://api.smartrecruiters.com/v1/companies/{token}/postings?country=au&limit=100
- detail: GET https://api.smartrecruiters.com/v1/companies/{token}/postings/{id} (jobAd sections)."""

from dataclasses import replace

from seekhunter.domain import JobData, normalize_work_type, seek_location
from seekhunter.sources.ats.base import Company, get_json, parse_iso, radar_job, require_token

API = "https://api.smartrecruiters.com/v1/companies"
PAGE = 100
MAX_PAGES = 5
_SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def _location(loc: dict) -> str:
    full = loc.get("fullLocation") or ", ".join(
        p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p)
    text = seek_location(full.replace(", ,", ","))
    if (loc.get("country") or "").lower() == "au" and "australia" not in text.lower():
        text = f"{text}, Australia" if text else "Australia"
    if loc.get("remote") and "remote" not in text.lower():
        text = f"{text} (remote)"
    return text


def parse_postings(payload: dict, company: Company, token: str) -> list[JobData]:
    out = []
    for p in payload.get("content") or []:
        pid = p.get("id")
        if not pid:
            continue
        identifier = (p.get("company") or {}).get("identifier") or token
        out.append(radar_job(
            ats="smartrecruiters", ext=str(pid), title=p.get("name") or "", company=company,
            location=_location(p.get("location") or {}),
            url=f"https://jobs.smartrecruiters.com/{identifier}/{pid}",
            work_type=normalize_work_type((p.get("typeOfEmployment") or {}).get("label")),
            listed_at=parse_iso(p.get("releasedDate")),
        ))
    return out


def parse_detail(payload: dict) -> tuple[str, str | None]:
    sections = ((payload.get("jobAd") or {}).get("sections")) or {}
    parts = []
    for key in _SECTIONS:
        sec = sections.get(key) or {}
        if sec.get("text"):
            parts.append(f"<h3>{sec.get('title') or ''}</h3>{sec['text']}")
    return "\n".join(parts), payload.get("postingUrl")


class SmartRecruitersClient:
    ats = "smartrecruiters"

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def list_jobs(self, company: Company) -> list[JobData]:
        token = require_token(company, self.ats)
        jobs: list[JobData] = []
        for page in range(MAX_PAGES):
            params = {"country": "au", "limit": PAGE, "offset": page * PAGE}
            payload = get_json(self.client.get(f"{API}/{token}/postings", params=params),
                               f"smartrecruiters {token}")
            jobs.extend(parse_postings(payload, company, token))
            if (page + 1) * PAGE >= int(payload.get("totalFound") or 0):
                break
        return jobs

    def details(self, job: JobData) -> JobData:
        if job.description_html:
            return job
        identifier = job.url.rstrip("/").split("/")[-2]
        pid = job.external_id.removeprefix("smartrecruiters:")
        payload = get_json(self.client.get(f"{API}/{identifier}/postings/{pid}"),
                           f"smartrecruiters {identifier}/{pid}")
        desc, url = parse_detail(payload)
        return replace(job, description_html=desc or job.description_html, url=url or job.url)
