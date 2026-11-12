"""Workday's candidate-experience (CXS) JSON API, what *.myworkdayjobs.com pages call themselves:
- list:   POST https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
          body {"appliedFacets":{},"limit":20,"offset":0,"searchText":""}  (newest first)
- detail: GET  .../wday/cxs/{tenant}/{site}{externalPath}

`ats_token` is "<tenant>.wd<n>/<site>", e.g. "telstra.wd3/Telstra_Careers". Listings only carry
title, a short location text and "Posted N Days Ago"; the body and country come from the detail."""

import re
from dataclasses import replace
from datetime import datetime, timedelta

from seekhunter.domain import JobData, normalize_work_type
from seekhunter.models import utcnow
from seekhunter.sources.ats.base import ATSError, Company, get_json, is_australian, parse_iso, radar_job

PAGE = 20
MAX_PAGES = 5
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
_TOKEN = re.compile(r"^([a-z0-9-]+)\.(wd\d+)/([A-Za-z0-9_-]+)$", re.IGNORECASE)
_DAYS_AGO = re.compile(r"(\d+)\+?\s+days?\s+ago", re.IGNORECASE)


def parse_token(token: str | None) -> tuple[str, str, str]:
    m = _TOKEN.match((token or "").strip())
    if not m:
        raise ATSError(f"workday: bad token {token!r} (want '<tenant>.wd<n>/<site>')")
    return m.group(1), m.group(2), m.group(3)


def host_and_api(token: str | None) -> tuple[str, str, str]:
    tenant, wd, site = parse_token(token)
    host = f"https://{tenant}.{wd}.myworkdayjobs.com"
    return host, f"{host}/wday/cxs/{tenant}/{site}", site


def parse_posted_on(text: str | None, now: datetime) -> datetime | None:
    t = (text or "").lower()
    if "today" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = _DAYS_AGO.search(t)
    return now - timedelta(days=int(m.group(1))) if m else None


def parse_list(payload: dict, company: Company, now: datetime) -> list[JobData]:
    host, _, site = host_and_api(company.ats_token)
    tenant = parse_token(company.ats_token)[0]
    out = []
    for p in payload.get("jobPostings") or []:
        path = p.get("externalPath")
        if not path:
            continue
        out.append(radar_job(
            ats="workday", ext=f"{tenant}:{path.rstrip('/').rsplit('/', 1)[-1]}",
            title=p.get("title") or "", company=company, location=p.get("locationsText") or "",
            url=f"{host}/{site}{path}", listed_at=parse_posted_on(p.get("postedOn"), now),
        ))
    return out


def parse_detail(payload: dict, job: JobData) -> JobData:
    info = payload.get("jobPostingInfo") or {}
    country = ((info.get("country") or {}).get("descriptor")) or ""
    loc = info.get("location") or job.location
    extra = [x for x in info.get("additionalLocations") or [] if x]
    if not is_australian(loc):
        loc = next((x for x in extra if is_australian(x)), loc)
    if country == "Australia" and not is_australian(loc):
        loc = f"{loc}, Australia" if loc else "Australia"
    elif country and country != "Australia" and country.lower() not in loc.lower():
        loc = f"{loc}, {country}" if loc else country
    work_type = normalize_work_type(info.get("timeType"))
    return replace(
        job, description_html=info.get("jobDescription") or job.description_html, location=loc,
        work_type=work_type if work_type != "unknown" else job.work_type,
        listed_at=parse_iso(info.get("startDate")) or job.listed_at,
        url=info.get("externalUrl") or job.url,
    )


class WorkdayClient:
    ats = "workday"

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client
        self._api_by_tenant: dict[str, str] = {}

    def list_jobs(self, company: Company) -> list[JobData]:
        _, api, _ = host_and_api(company.ats_token)
        self._api_by_tenant[parse_token(company.ats_token)[0]] = api
        now = utcnow()
        jobs: list[JobData] = []
        total = 0
        for page in range(MAX_PAGES):
            body = {"appliedFacets": {}, "limit": PAGE, "offset": page * PAGE, "searchText": ""}
            payload = get_json(self.client.post(f"{api}/jobs", json=body, headers=HEADERS),
                               f"workday {company.ats_token}")
            jobs.extend(parse_list(payload, company, now))
            # Workday only reports `total` on the first page (later pages say 0).
            total = total or int(payload.get("total") or 0)
            if (page + 1) * PAGE >= total or not payload.get("jobPostings"):
                break
        return jobs

    def details(self, job: JobData) -> JobData:
        if job.description_html:
            return job
        api, path = self._detail_target(job)
        payload = get_json(self.client.get(f"{api}{path}", headers={"Accept": "application/json"}),
                           f"workday {job.external_id}")
        return parse_detail(payload, job)

    def _detail_target(self, job: JobData) -> tuple[str, str]:
        # url: https://{tenant}.wdN.myworkdayjobs.com/{site}/job/...  -> api + "/job/..."
        m = re.match(r"^(https://([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com)/([^/]+)(/job/.+)$", job.url,
                     re.IGNORECASE)
        if not m:
            raise ATSError(f"workday: can't derive the detail URL from {job.url}")
        host, tenant, site, path = m.groups()
        return self._api_by_tenant.get(tenant, f"{host}/wday/cxs/{tenant}/{site}"), path
