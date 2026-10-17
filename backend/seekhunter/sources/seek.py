from dataclasses import replace
from datetime import datetime

from seekhunter.domain import JobData, normalize_work_type
from seekhunter.models import SearchProfile

SEARCH_URL = "https://www.seek.com.au/api/jobsearch/v5/search"
GRAPHQL_URL = "https://www.seek.com.au/graphql"
PAGE_SIZE = 22
WORKTYPE_IDS = {"full_time": "242", "part_time": "243", "contract": "244", "casual": "245"}
DETAILS_QUERY = (
    "query jobDetails($jobId: ID!) { jobDetails(id: $jobId) { job { id content(platform: WEB) } } }"
)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def parse_search_item(item: dict) -> JobData:
    job_id = str(item["id"])
    locations = item.get("locations") or []
    teaser = " ".join([item.get("teaser") or "", *(item.get("bulletPoints") or [])]).strip()
    return JobData(
        source="seek",
        external_id=job_id,
        title=item.get("title", ""),
        company=(item.get("advertiser") or {}).get("description") or item.get("companyName") or "",
        location=locations[0]["label"] if locations else "",
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
            payload = self.client.get(SEARCH_URL, params=params).json()
            jobs.extend(parse_search_item(item) for item in payload.get("data") or [])
            if page * PAGE_SIZE >= int(payload.get("totalCount") or 0):
                break
        return jobs

    def details(self, job: JobData) -> JobData:
        payload = self.client.post(
            GRAPHQL_URL,
            json={
                "operationName": "jobDetails", "variables": {"jobId": job.external_id},
                "query": DETAILS_QUERY,
            },
            headers={"seek-request-brand": "seek", "seek-request-country": "AU"},
        ).json()
        content = ((((payload.get("data") or {}).get("jobDetails") or {}).get("job")) or {}).get("content")
        return replace(job, description_html=content) if content else job
