"""Indeed Australia via JobSpy (python-jobspy, MIT): one GraphQL search per profile, which already
includes each ad's full description, so `details()` has nothing left to fetch."""

import hashlib
import logging
import math
import random
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from seekhunter.domain import JobData, normalize_location
from seekhunter.http import SourceBlocked
from seekhunter.models import SearchProfile

log = logging.getLogger(__name__)

RESULTS_PER_PAGE = 25
HOURS_OLD = 168
_STATES = {"SA", "VIC", "NSW", "QLD", "WA", "TAS", "NT", "ACT"}
# JobSpy JobType values -> ours (Indeed AU's "temporary" is the closest thing to casual work).
_JOB_TYPES = {"fulltime": "full_time", "parttime": "part_time", "contract": "contract",
              "temporary": "contract"}
# Ours -> the single JobSpy `job_type` filter Indeed accepts.
_JOBSPY_TYPES = {"full_time": "fulltime", "part_time": "parttime", "contract": "contract",
                 "casual": "temporary"}
_INTERVALS = {"hourly": "hour", "daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}


def _clean(value: Any) -> Any:
    """JobSpy rows come from a DataFrame: missing values are NaN/None/NaT."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        import pandas as pd

        if value is pd.NaT:
            return None
    except ImportError:  # pragma: no cover
        pass
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _location(raw: str | None) -> str:
    """'Gepps Cross, SA, Australia' -> 'Gepps Cross SA' (SEEK style)."""
    loc = normalize_location(raw or "")
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if len(parts) >= 2 and parts[-1].upper() in _STATES:
        return f"{', '.join(parts[:-1])} {parts[-1].upper()}"
    return ", ".join(parts)


def _work_type(raw: str | None) -> str:
    for part in (raw or "").split(","):
        kind = _JOB_TYPES.get(part.strip().lower())
        if kind:
            return kind
    return "unknown"


def _money(value: float) -> str:
    return f"${value:,.0f}"


def salary_label(low: float | None, high: float | None, interval: str | None) -> str | None:
    low, high = _clean(low), _clean(high)
    if not low and not high:
        return None
    unit = _INTERVALS.get((_clean(interval) or "").lower())
    amount = f"{_money(low)} – {_money(high)}" if low and high and low != high else _money(low or high)
    return f"{amount} per {unit}" if unit else amount


def _listed_at(value: Any) -> datetime | None:
    value = _clean(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def parse_row(row: dict) -> JobData:
    url = _clean(row.get("job_url")) or ""
    raw_id = _clean(row.get("id"))
    external_id = (str(raw_id).removeprefix("in-") if raw_id
                   else hashlib.sha1(url.encode()).hexdigest()[:16])
    emails = _clean(row.get("emails"))
    return JobData(
        source="indeed",
        external_id=external_id,
        title=_clean(row.get("title")) or "",
        company=_clean(row.get("company")) or "",
        location=_location(_clean(row.get("location"))),
        work_type=_work_type(_clean(row.get("job_type"))),
        url=url,
        salary_label=salary_label(row.get("min_amount"), row.get("max_amount"), row.get("interval")),
        listed_at=_listed_at(row.get("date_posted")),
        description_html=_clean(row.get("description")) or "",
        contact_email=str(emails).split(",")[0].strip() if emails else None,
    )


def indeed_location(profile_location: str) -> str:
    """Search-profile location -> Indeed's `where`: 'All Adelaide SA' -> 'Adelaide, SA'."""
    loc = profile_location.removeprefix("All ").strip()
    parts = loc.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].upper() in _STATES:
        return f"{parts[0]}, {parts[1].upper()}"
    return loc


class _Counter:
    """Stands in for PoliteClient's counters (JobSpy runs its own HTTP sessions)."""

    def __init__(self) -> None:
        self.request_count = 0
        self.blocked_count = 0


class IndeedSource:
    name = "indeed"

    def __init__(self, scrape: Callable[..., Any] | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 min_delay: float = 3.0, max_delay: float = 6.0) -> None:
        self._scrape = scrape
        self.sleep = sleep
        self.min_delay, self.max_delay = min_delay, max_delay
        self.client = _Counter()

    def _scrape_jobs(self, **kw: Any) -> Any:
        if self._scrape is None:
            from jobspy import scrape_jobs

            self._scrape = scrape_jobs
        return self._scrape(**kw)

    def search(self, profile: SearchProfile, max_pages: int) -> list[JobData]:
        wanted = set(profile.work_types)
        kw: dict[str, Any] = {
            "site_name": ["indeed"],
            "search_term": profile.keywords,
            "location": indeed_location(profile.location),
            "country_indeed": "australia",
            "hours_old": HOURS_OLD,
            "results_wanted": RESULTS_PER_PAGE * max(1, max_pages),
            "description_format": "html",
            "verbose": 0,
        }
        # Indeed filters on a single job type; with several wanted, filter the results instead.
        if len(wanted) == 1 and next(iter(wanted)) in _JOBSPY_TYPES:
            kw["job_type"] = _JOBSPY_TYPES[next(iter(wanted))]
        if self.client.request_count:
            self.sleep(random.uniform(self.min_delay, self.max_delay))
        self.client.request_count += 1
        try:
            df = self._scrape_jobs(**kw)
        except Exception as e:  # noqa: BLE001  JobSpy raises assorted network/parse errors
            self.client.blocked_count += 1
            raise SourceBlocked(f"indeed: {type(e).__name__}: {e}") from e
        errors = (getattr(df, "attrs", None) or {}).get("errors") or {}
        if errors.get("indeed"):
            self.client.blocked_count += 1
            raise SourceBlocked(f"indeed: {errors['indeed']}")
        jobs = [parse_row(r) for r in df.to_dict("records")]
        jobs = [j for j in jobs if j.url and j.title]
        if wanted and "job_type" not in kw:
            jobs = [j for j in jobs if j.work_type in wanted or j.work_type == "unknown"]
        return jobs

    def details(self, job: JobData) -> JobData:
        return job
