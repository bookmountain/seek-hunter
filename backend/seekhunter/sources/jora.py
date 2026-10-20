import re
from dataclasses import replace
from datetime import datetime, timedelta
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from seekhunter.domain import JobData, normalize_work_type
from seekhunter.models import SearchProfile, utcnow

BASE = "https://au.jora.com"
_POSTED = re.compile(r"(\d+)\s*([mhdw])(?!o)", re.IGNORECASE)
_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_posted(text: str, now: datetime) -> datetime | None:
    if not text:
        return None
    m = _POSTED.search(text)
    if not m:
        return now if "just" in text.lower() or "today" in text.lower() else None
    return now - timedelta(**{_UNITS[m.group(2).lower()]: int(m.group(1))})


def _text(node) -> str:  # noqa: ANN001
    return node.text(strip=True) if node else ""


def parse_search_html(html: str, now: datetime) -> tuple[list[JobData], bool]:
    tree = LexborHTMLParser(html)
    jobs: list[JobData] = []
    for card in tree.css("div.job-card"):
        link = card.css_first("h2.job-title a.job-link")
        card_id = card.attributes.get("id") or ""
        if not link or not card_id.startswith("r_"):
            continue
        badges = [b.text(strip=True) for b in card.css(".badge.-default-badge .content")]
        salary = next((b for b in badges if "$" in b), None)
        work_type = next((normalize_work_type(b) for b in badges if normalize_work_type(b) != "unknown"),
                         "unknown")
        href = (link.attributes.get("href") or "").split("?")[0]
        if not href.startswith("/job/"):
            continue
        jobs.append(JobData(
            source="jora", external_id=card_id[2:], title=link.text(strip=True),
            company=_text(card.css_first(".job-company")), location=_text(card.css_first(".job-location")),
            work_type=work_type, url=urljoin(BASE, href), salary_label=salary,
            listed_at=parse_posted(_text(card.css_first(".job-listed-date")), now),
            teaser=card.css_first(".job-abstract").text(separator=" ", strip=True)
            if card.css_first(".job-abstract") else "",
        ))
    return jobs, tree.css_first("a.next-page-button") is not None


def parse_detail_html(html: str) -> tuple[str, str]:
    tree = LexborHTMLParser(html)
    container = tree.css_first("#job-description-container")
    scope = tree.css_first(".job-view-content") or tree
    badges = [b.text(strip=True) for b in scope.css(".badge .content")]
    work_type = next(
        (normalize_work_type(b) for b in badges if normalize_work_type(b) != "unknown"), "unknown")
    return (container.html if container else ""), work_type


def parse_closed(html: str) -> bool | None:
    """Jora keeps serving a closed ad with a "This job is no longer available" error banner."""
    tree = LexborHTMLParser(html)
    banner = tree.css_first(".flash-container.error")
    if banner and "no longer available" in banner.text().lower():
        return True
    return False if tree.css_first("#job-description-container") else None


class JoraSource:
    name = "jora"

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def search(self, profile: SearchProfile, max_pages: int) -> list[JobData]:
        location = profile.location.removeprefix("All ").strip()
        wanted = set(profile.work_types)
        jobs: list[JobData] = []
        for page in range(1, max_pages + 1):
            params = {"q": profile.keywords, "l": location, "sp": "search", "a": "7d"}
            if page > 1:
                params["p"] = page
            resp_text = self.client.get(f"{BASE}/j", params=params).text
            page_jobs, has_next = parse_search_html(resp_text, utcnow())
            jobs.extend(
                j for j in page_jobs if not wanted or j.work_type in wanted or j.work_type == "unknown")
            if not has_next:
                break
        return jobs

    def is_closed(self, job: JobData) -> bool | None:
        resp = self.client.get(job.url)
        if resp.status_code in (404, 410):
            return True
        return parse_closed(resp.text) if resp.status_code == 200 else None

    def details(self, job: JobData) -> JobData:
        desc, work_type = parse_detail_html(self.client.get(job.url).text)
        return replace(job, description_html=desc or job.description_html,
                       work_type=job.work_type if job.work_type != "unknown" else work_type)
