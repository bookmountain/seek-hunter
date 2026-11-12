"""Shared bits for the Company Radar's ATS clients.

Every client has the same shape: `list_jobs(company) -> list[JobData]` (source "radar", external
ids prefixed with the ATS name, description included when the feed has it) and
`details(job) -> JobData` (fetches the ad body for feeds whose listing omits it; identity
otherwise). Location / IT-relevance filtering happens in `seekhunter.radar`, the same way for all.
"""

import re
from datetime import UTC, datetime
from typing import Any, Protocol

from seekhunter.domain import JobData

RADAR_SOURCE = "radar"


class ATSError(Exception):
    """The board answered with something other than a usable job feed (404, HTML, bad JSON)."""


class Company(Protocol):
    name: str
    ats_token: str | None


class ATSClient(Protocol):
    ats: str

    def list_jobs(self, company: Company) -> list[JobData]: ...

    def details(self, job: JobData) -> JobData: ...


def get_json(resp: Any, what: str) -> Any:
    status = getattr(resp, "status_code", 200)
    if status != 200:
        raise ATSError(f"{what}: HTTP {status}")
    try:
        return resp.json()
    except ValueError as e:
        raise ATSError(f"{what}: not JSON") from e


def require_token(company: Company, ats: str) -> str:
    token = (company.ats_token or "").strip()
    if not token:
        raise ATSError(f"{ats}: no board token set for {company.name}")
    return token


def parse_iso(value: str | None) -> datetime | None:
    """ISO-8601 (with or without offset/Z) -> naive UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def from_millis(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


_AU_CITIES = (
    "adelaide", "melbourne", "sydney", "perth", "brisbane", "canberra", "hobart", "darwin",
    "gold coast", "sunshine coast", "newcastle", "wollongong", "geelong", "townsville", "cairns",
    "toowoomba", "ballarat", "bendigo", "launceston", "parramatta", "north sydney",
    "macquarie park", "mawson lakes", "mount barker", "whyalla", "port augusta", "alice springs",
)
_AU_STATES = (
    "south australia", "new south wales", "victoria", "queensland", "tasmania",
    "western australia", "northern territory", "australian capital territory",
)
_AU_TOKENS = re.compile(
    r"\baustralia\b|\baus\b|\bau\b|\bnsw\b|\bvic\b|\bqld\b|\btas\b|\bact\b|\banz\b|\bapac\b",
    re.IGNORECASE,
)
# Same-named places elsewhere ("Perth, Scotland", "Melbourne, FL", "Sydney, Nova Scotia").
_NOT_AU = re.compile(
    r"\b(scotland|united kingdom|uk|florida|fl|nova scotia|ns|canada|usa|united states|ontario)\b",
    re.IGNORECASE,
)


def is_australian(location: str | None) -> bool:
    """Best-effort: does a free-text ATS location point at Australia? ("Sydney", "AU - Melbourne",
    "Adelaide, South Australia", "Australia (Flexible)", "Remote - ANZ")."""
    loc = (location or "").strip()
    if not loc:
        return False
    low = loc.lower()
    if "australia" in low:
        return True
    if _NOT_AU.search(loc):
        return False
    if _AU_TOKENS.search(loc):
        return True
    return any(re.search(rf"\b{re.escape(c)}\b", low) for c in (*_AU_CITIES, *_AU_STATES))


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def radar_job(*, ats: str, ext: str, title: str, company: Company, location: str, url: str,
              work_type: str = "unknown", listed_at: datetime | None = None,
              description_html: str = "", salary_label: str | None = None) -> JobData:
    return JobData(
        source=RADAR_SOURCE, external_id=f"{ats}:{ext}", title=(title or "").strip(),
        company=company.name, location=location or "", work_type=work_type, url=url,
        salary_label=salary_label, listed_at=listed_at, description_html=description_html or "",
    )
