import logging
from dataclasses import replace
from datetime import datetime

from seekhunter.domain import JobData, normalize_work_type
from seekhunter.http import SourceBlocked
from seekhunter.models import SearchProfile

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.seek.com.au/api/jobsearch/v5/search"
GRAPHQL_URL = "https://www.seek.com.au/graphql"
PAGE_SIZE = 22
WORKTYPE_IDS = {"full_time": "242", "part_time": "243", "contract": "244", "casual": "245"}
_INSIGHTS_FIELDS = (
    "insights { __typename "
    "... on ApplicantCount { count countLabel(locale: $locale) volumeLabel(locale: $locale) } "
    "... on ApplicantsWithResumePercentage { percentage } "
    "... on ApplicantsWithCoverLetterPercentage { percentage } }"
)
DETAILS_QUERY = (
    "query jobDetails($jobId: ID!, $locale: Locale!) { jobDetails(id: $jobId) { "
    "job { id content(platform: WEB) contactMatches { type value } } " + _INSIGHTS_FIELDS + " } }"
)
INSIGHTS_QUERY = (
    "query jobInsights($jobId: ID!, $locale: Locale!) { jobDetails(id: $jobId) { " + _INSIGHTS_FIELDS + " } }"
)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _parse_json(resp) -> dict:  # noqa: ANN001
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceBlocked("non-JSON response from SEEK") from exc


def _parse_contacts(matches: list[dict]) -> tuple[str | None, str | None]:
    phone = next((m.get("value") for m in matches if m.get("type") == "Phone"), None)
    email = next((m.get("value") for m in matches if m.get("type") == "Email"), None)
    return phone, email


def _parse_insights(insights: list[dict]) -> dict:
    """Parses SEEK's `insights` union list into our flat field names. An empty list (SEEK hasn't
    published applicant stats for this ad) yields an empty dict, not an error."""
    result: dict = {}
    for entry in insights:
        typename = entry.get("__typename")
        if typename == "ApplicantCount":
            result["applicant_count"] = entry.get("count")
            result["applicant_volume"] = entry.get("volumeLabel")
        elif typename == "ApplicantsWithResumePercentage":
            result["resume_pct"] = entry.get("percentage")
        elif typename == "ApplicantsWithCoverLetterPercentage":
            result["cover_letter_pct"] = entry.get("percentage")
    return result


def parse_search_item(item: dict) -> JobData:
    job_id = str(item["id"])
    location = ((item.get("locations") or [{}])[0] or {}).get("label", "")
    teaser = " ".join([item.get("teaser") or "", *(item.get("bulletPoints") or [])]).strip()
    return JobData(
        source="seek",
        external_id=job_id,
        title=item.get("title", ""),
        company=(item.get("advertiser") or {}).get("description") or item.get("companyName") or "",
        location=location,
        work_type=normalize_work_type((item.get("workTypes") or [""])[0]),
        url=f"https://www.seek.com.au/job/{job_id}",
        salary_label=item.get("salaryLabel") or None,
        listed_at=_parse_dt(item.get("listingDate")),
        teaser=teaser,
    )


class SeekSource:
    name = "seek"

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def search(self, profile: SearchProfile, max_pages: int) -> list[JobData]:
        jobs: list[JobData] = []
        for page in range(1, max_pages + 1):
            params = {
                "siteKey": "AU-Main", "where": profile.location, "keywords": profile.keywords, "page": page,
                "pageSize": PAGE_SIZE, "daterange": 7, "locale": "en-AU",
            }
            ids = [WORKTYPE_IDS[w] for w in profile.work_types if w in WORKTYPE_IDS]
            if ids:
                params["worktype"] = ",".join(ids)
            payload = _parse_json(self.client.get(SEARCH_URL, params=params))
            items = payload.get("data") or []
            if not items:
                break
            jobs.extend(parse_search_item(item) for item in items if item.get("id") is not None)
            if page * PAGE_SIZE >= int(payload.get("totalCount") or 0):
                break
        return jobs

    def details(self, job: JobData) -> JobData:
        resp = self.client.post(
            GRAPHQL_URL,
            json={
                "operationName": "jobDetails", "variables": {"jobId": job.external_id, "locale": "en-AU"},
                "query": DETAILS_QUERY,
            },
            headers={"seek-request-brand": "seek", "seek-request-country": "AU"},
        )
        payload = _parse_json(resp)
        if "errors" in payload:
            logger.warning("SEEK details for job %s returned errors: %s", job.external_id, payload["errors"])
            return job
        job_details = (payload.get("data") or {}).get("jobDetails") or {}
        job_data = job_details.get("job") or {}
        content = job_data.get("content")
        phone, email = _parse_contacts(job_data.get("contactMatches") or [])
        updates = {}
        if content:
            updates["description_html"] = content
        if phone:
            updates["contact_phone"] = phone
        if email:
            updates["contact_email"] = email
        updates.update(_parse_insights(job_details.get("insights") or []))
        return replace(job, **updates) if updates else job

    def insights(self, external_id: str) -> dict | None:
        """Lighter-weight refresh query for insights only (applicant count, resume/cover-letter %),
        used when re-checking a job seen in an earlier run. Returns `None` on a GraphQL error
        (logged, not raised); an empty dict means SEEK has no insights published for this ad."""
        resp = self.client.post(
            GRAPHQL_URL,
            json={
                "operationName": "jobInsights", "variables": {"jobId": external_id, "locale": "en-AU"},
                "query": INSIGHTS_QUERY,
            },
            headers={"seek-request-brand": "seek", "seek-request-country": "AU"},
        )
        payload = _parse_json(resp)
        if "errors" in payload:
            logger.warning("SEEK insights for job %s returned errors: %s", external_id, payload["errors"])
            return None
        job_details = (payload.get("data") or {}).get("jobDetails") or {}
        return _parse_insights(job_details.get("insights") or [])
