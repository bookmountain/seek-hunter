import re
from dataclasses import replace
from datetime import datetime

from selectolax.lexbor import LexborHTMLParser

from seekhunter.domain import JobData, normalize_work_type
from seekhunter.models import SearchProfile

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting"
DATE_FILTER_7D = "r604800"

_URN_ID = re.compile(r"urn:li:jobPosting:(\d+)")
_APPLICANT_NUM = re.compile(r"(\d[\d,]*)")

# SearchProfile.location -> LinkedIn's free-text `location` guest-search param.
LOCATION_MAP = {
    "All Adelaide SA": "Adelaide, South Australia, Australia",
    "All Melbourne VIC": "Melbourne, Victoria, Australia",
    "All Sydney NSW": "Sydney, New South Wales, Australia",
    "All Perth WA": "Perth, Western Australia, Australia",
    "All Brisbane QLD": "Brisbane, Queensland, Australia",
}

# Our work_type -> LinkedIn's f_JT job-type code. LinkedIn has no "casual" concept; the closest
# match is "Temporary".
WORKTYPE_CODES = {"full_time": "F", "part_time": "P", "contract": "C", "casual": "T"}


def _job_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_search_html(html: str) -> list[JobData]:
    """Parses a page of LinkedIn's guest `seeMoreJobPostings` search fragment: one `<li>` per
    card. Cards with no parseable `urn:li:jobPosting:<id>` are skipped. `work_type` is always
    "unknown" here — LinkedIn's search cards don't carry it, only the detail page does (see
    `parse_detail_html`)."""
    tree = LexborHTMLParser(html)
    jobs: list[JobData] = []
    for card in tree.css("div.base-search-card"):
        urn = card.attributes.get("data-entity-urn") or ""
        m = _URN_ID.search(urn)
        if not m:
            continue
        job_id = m.group(1)
        title = card.css_first("h3.base-search-card__title")
        company = card.css_first("h4.base-search-card__subtitle a")
        location = card.css_first("span.job-search-card__location")
        # The "posted today" variant uses a `--new` modifier class instead of the plain one.
        listed = card.css_first('time[class^="job-search-card__listdate"]')
        jobs.append(JobData(
            source="linkedin", external_id=job_id,
            title=title.text(strip=True) if title else "",
            company=company.text(strip=True) if company else "",
            location=location.text(strip=True) if location else "",
            work_type="unknown", url=_job_url(job_id),
            listed_at=_parse_dt(listed.attributes.get("datetime")) if listed else None,
        ))
    return jobs


def parse_applicant_count(text: str | None) -> int | None:
    m = _APPLICANT_NUM.search(text or "")
    return int(m.group(1).replace(",", "")) if m else None


def parse_detail_html(html: str) -> tuple[str, str, int | None]:
    """Returns `(description_html, work_type, applicant_count)` from a LinkedIn guest job-detail
    page. Any missing section degrades gracefully: `""`, `"unknown"`, `None` respectively."""
    tree = LexborHTMLParser(html)
    container = tree.css_first("div.show-more-less-html__markup")

    work_type = "unknown"
    for item in tree.css("ul.description__job-criteria-list li.description__job-criteria-item"):
        header = item.css_first("h3.description__job-criteria-subheader")
        value = item.css_first("span.description__job-criteria-text")
        if header and value and "employment type" in header.text(strip=True).lower():
            work_type = normalize_work_type(value.text(strip=True))
            break

    applicants_node = tree.css_first(".num-applicants__caption")
    applicant_count = parse_applicant_count(applicants_node.text(strip=True)) if applicants_node else None

    return (container.html if container else ""), work_type, applicant_count


def parse_closed(html: str) -> bool | None:
    tree = LexborHTMLParser(html)
    text = tree.body.text().lower() if tree.body else ""
    if "no longer accepting applications" in text:
        return True
    return False if tree.css_first("div.show-more-less-html__markup") else None


class LinkedInSource:
    name = "linkedin"

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def search(self, profile: SearchProfile, max_pages: int) -> list[JobData]:
        location = LOCATION_MAP.get(profile.location, profile.location.removeprefix("All ").strip())
        codes = sorted({WORKTYPE_CODES[w] for w in profile.work_types if w in WORKTYPE_CODES})
        jobs: list[JobData] = []
        start = 0
        for _ in range(max_pages):
            params = {
                "keywords": profile.keywords, "location": location, "f_TPR": DATE_FILTER_7D, "start": start,
            }
            if codes:
                params["f_JT"] = ",".join(codes)
            html = self.client.get(SEARCH_URL, params=params).text
            page_jobs = parse_search_html(html)
            if not page_jobs:
                break
            jobs.extend(page_jobs)
            start += len(page_jobs)
        return jobs

    def is_closed(self, job: JobData) -> bool | None:
        resp = self.client.get(f"{DETAIL_URL}/{job.external_id}")
        if resp.status_code in (404, 410):
            return True
        return parse_closed(resp.text) if resp.status_code == 200 else None

    def details(self, job: JobData) -> JobData:
        html = self.client.get(f"{DETAIL_URL}/{job.external_id}").text
        description_html, work_type, applicant_count = parse_detail_html(html)
        updates: dict = {}
        if description_html:
            updates["description_html"] = description_html
        if work_type != "unknown":
            updates["work_type"] = work_type
        if applicant_count is not None:
            updates["applicant_count"] = applicant_count
        # LinkedIn's guest pages have no SEEK-style volume label; applicant_volume intentionally
        # stays at its default (None) rather than being set to anything LinkedIn-specific.
        return replace(job, **updates) if updates else job
