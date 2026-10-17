import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from seekhunter import repo
from seekhunter.domain import FLEXIBLE_WORK_TYPES
from seekhunter.http import SourceBlocked
from seekhunter.models import MarketJob, SearchProfile, utcnow
from seekhunter.skills import extract_skills

log = logging.getLogger(__name__)

CITY_LOCATIONS: dict[str, str] = {
    "adelaide": "All Adelaide SA",
    "melbourne": "All Melbourne VIC",
    "sydney": "All Sydney NSW",
    "perth": "All Perth WA",
}
CITY_ORDER = ["adelaide", "melbourne", "sydney", "perth"]
SEARCH_PAGES = 2
SEARCH_DATERANGE = 14
SNAPSHOT_WINDOW_DAYS = 14

# ------------------------------------------------------------------ role family

ROLE_RULES: list[tuple[str, list[str]]] = [
    ("ai_ml", ["ai", "machine learning", "ml", "llm", "data scientist"]),
    ("data", ["data engineer", "data analyst", "analytics", "bi", "etl"]),
    ("devops_cloud", ["devops", "cloud", "platform", "sre", "infrastructure"]),
    ("mobile", ["ios", "android", "mobile", "react native", "flutter"]),
    ("qa", ["qa", "test", "tester", "quality"]),
    ("it_support", ["support", "helpdesk", "help desk", "service desk", "desktop", "technician"]),
    ("frontend", ["front end", "frontend", "front-end", "ui developer"]),
    ("backend", ["back end", "backend", "back-end", "api"]),
    ("fullstack", ["full stack", "fullstack", "full-stack", "software engineer", "software developer",
                   "developer", "programmer"]),
]
_ROLE_PATTERNS: list[tuple[str, list[re.Pattern[str]]]] = [
    (family, [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in kws])
    for family, kws in ROLE_RULES
]


def role_family(title: str) -> str:
    for family, patterns in _ROLE_PATTERNS:
        if any(p.search(title) for p in patterns):
            return family
    return "other"


# ------------------------------------------------------------------ salary normalisation

_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s?(k)?", re.IGNORECASE)
_PERIOD_HOUR = re.compile(r"\bp\.?\s*h\.?\b|per\s+hour|/\s*hr\b|hourly", re.IGNORECASE)
_PERIOD_DAY = re.compile(r"\bp\.?\s*d\.?\b|per\s+day|/\s*day\b|daily", re.IGNORECASE)
_PERIOD_ANNUAL = re.compile(
    r"\bp\.?\s*a\.?\b|per\s+annum|per\s+year|annually|/\s*yr\b|yearly", re.IGNORECASE)
_UP_TO = re.compile(r"\bup\s+to\b", re.IGNORECASE)

ANNUAL_HOURS_PER_YEAR = 1976
HOURS_PER_DAY = 7.6


def normalize_salary_hourly(label: str | None) -> tuple[float | None, float | None]:
    """Parses a SEEK salary label into (min, max) AUD/hour. Unparseable labels (no `$` amount, or
    an ambiguous bare number with no period indicator and no `k` shorthand) return (None, None)."""
    if not label:
        return None, None
    text = label.replace("–", "-").replace("—", "-")
    matches = _MONEY.findall(text)
    if not matches:
        return None, None
    values = [float(num.replace(",", "")) * (1000 if k else 1) for num, k in matches]
    up_to = bool(_UP_TO.search(text))
    if len(values) == 1:
        lo, hi = (None if up_to else values[0]), values[0]
    else:
        lo, hi = sorted(values[:2])

    if _PERIOD_HOUR.search(text):
        divisor = 1.0
    elif _PERIOD_DAY.search(text):
        divisor = HOURS_PER_DAY
    elif _PERIOD_ANNUAL.search(text) or any(k for _, k in matches) or hi >= 1000:
        divisor = ANNUAL_HOURS_PER_YEAR
    else:
        return None, None
    return (lo / divisor if lo is not None else None), hi / divisor


def _hourly_value(job: MarketJob) -> float | None:
    if job.salary_min_hourly is not None and job.salary_max_hourly is not None:
        return (job.salary_min_hourly + job.salary_max_hourly) / 2
    if job.salary_max_hourly is not None:
        return job.salary_max_hourly
    return job.salary_min_hourly


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct
    f, c = int(k // 1), int(-(-k // 1))
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def salary_percentiles(values: list[float]) -> dict:
    vals = sorted(values)
    return {"p25": _percentile(vals, 0.25), "p50": _percentile(vals, 0.5), "p75": _percentile(vals, 0.75),
           "n": len(vals)}


# ------------------------------------------------------------------ crawl

def run_market_crawl(session, seek_source, settings, cities: list[str] | None = None,  # noqa: ANN001
                     now: datetime | None = None, dry_run: bool = False) -> dict:
    """Crawls SEEK for market data across cities, independent of the main `jobs` crawl: upserts
    `market_jobs`, fetches details for a capped number of not-yet-detailed jobs per city, then
    writes today's `market_snapshots` row per city. Never touches `jobs`/notifications.

    `dry_run=True` performs the searches (to validate connectivity/parsing) but makes no
    database writes."""
    now = now or utcnow()
    cities = cities or settings.market_cities
    report: dict = {}
    for city in cities:
        location = CITY_LOCATIONS.get(city)
        if not location:
            continue
        city_report = {"found": 0, "new": 0, "details_fetched": 0, "error": None}
        try:
            for keyword in settings.market_keywords:
                profile = SearchProfile(name="market", keywords=keyword, location=location, work_types=[])
                jobs = seek_source.search(profile, SEARCH_PAGES, daterange=SEARCH_DATERANGE)
                city_report["found"] += len(jobs)
                if dry_run:
                    continue
                for data in jobs:
                    salary_min, salary_max = normalize_salary_hourly(data.salary_label)
                    skills = sorted(extract_skills(f"{data.title} {data.teaser}"))
                    _, is_new = repo.upsert_market_job(
                        session, data, city, keyword, now, role_family=role_family(data.title),
                        skills=skills, salary_min_hourly=salary_min, salary_max_hourly=salary_max)
                    if is_new:
                        city_report["new"] += 1
            if not dry_run:
                pending = repo.market_jobs_needing_details(session, city, settings.market_details_per_city)
                for job in pending:
                    try:
                        details = seek_source.details(repo.to_market_jobdata(job))
                    except SourceBlocked as e:
                        city_report["error"] = str(e)
                        break
                    except Exception as e:  # noqa: BLE001  one bad detail page must not abort the crawl
                        log.warning("market details failed for seek %s: %s", job.external_id, e)
                        continue
                    extra = extract_skills(f"{job.title} {details.text}")
                    repo.apply_market_details(session, job, sorted(set(job.skills) | extra))
                    city_report["details_fetched"] += 1
                write_snapshot(session, city, now)
        except SourceBlocked as e:
            city_report["error"] = str(e)
        report[city] = city_report
    return report


# ------------------------------------------------------------------ snapshots

def compute_snapshot(jobs: list[MarketJob]) -> dict:
    total = len(jobs)
    detailed = [j for j in jobs if j.details_fetched]
    salary_values = [v for v in (_hourly_value(j) for j in jobs) if v is not None]
    return {
        "total": total,
        "detailed_count": len(detailed),
        "by_work_type": dict(Counter(j.work_type for j in jobs)),
        "by_role_family": dict(Counter(j.role_family for j in jobs)),
        "skill_counts": dict(Counter(s for j in detailed for s in j.skills)),
        "salary_percentiles": salary_percentiles(salary_values),
    }


def write_snapshot(session, city: str, now: datetime):  # noqa: ANN001
    since = now - timedelta(days=SNAPSHOT_WINDOW_DAYS)
    jobs = repo.market_jobs_scope(session, city=city, since=since)
    stats = compute_snapshot(jobs)
    date = datetime(now.year, now.month, now.day)
    return repo.save_market_snapshot(session, city, date, stats)


# ------------------------------------------------------------------ analysis

def overview(session, days: int = 14) -> list[dict]:  # noqa: ANN001
    since = utcnow() - timedelta(days=days)
    rows = []
    for city in CITY_ORDER:
        jobs = repo.market_jobs_scope(session, city=city, since=since)
        total = len(jobs)
        flexible = sum(1 for j in jobs if j.work_type in FLEXIBLE_WORK_TYPES)
        salary_values = [v for v in (_hourly_value(j) for j in jobs) if v is not None]
        pct = salary_percentiles(salary_values)
        rows.append({
            "city": city, "total": total, "flexible": flexible,
            "flexible_share": (flexible / total) if total else 0.0,
            "work_type_mix": dict(Counter(j.work_type for j in jobs)),
            "role_family_mix": dict(Counter(j.role_family for j in jobs)),
            "salary_p25": pct["p25"], "salary_p50": pct["p50"], "salary_p75": pct["p75"],
            "salary_sample_size": pct["n"],
            "detailed_sample_size": sum(1 for j in jobs if j.details_fetched),
        })
    return rows


def skill_demand(session, city: str, days: int = 14, role_family: str | None = None,  # noqa: ANN001
                 profile_skills: frozenset = frozenset(), top: int = 40) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    jobs = repo.market_jobs_scope(session, city=city, since=since, role_family=role_family,
                                  detailed_only=True)
    total = len(jobs)
    counts = Counter(s for j in jobs for s in j.skills)
    return [
        {"skill": skill, "count": count, "share": (count / total) if total else 0.0,
         "you_have": skill in profile_skills}
        for skill, count in counts.most_common(top)
    ]


def compare(session, skills: list[str], days: int = 14) -> list[dict]:  # noqa: ANN001
    since = utcnow() - timedelta(days=days)
    rows = []
    for city in CITY_ORDER:
        jobs = repo.market_jobs_scope(session, city=city, since=since, detailed_only=True)
        total = len(jobs)
        counts = Counter(s for j in jobs for s in j.skills)
        rows.append({
            "city": city, "shares": {sk: (counts.get(sk, 0) / total if total else 0.0) for sk in skills},
            "detailed_sample_size": total,
        })
    return rows


def gaps(session, city: str, days: int = 14, profile_skills: frozenset = frozenset(),  # noqa: ANN001
        top: int = 30) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    jobs = repo.market_jobs_scope(session, city=city, since=since, detailed_only=True)
    total = len(jobs)
    counts = Counter(s for j in jobs for s in j.skills if s not in profile_skills)
    result = []
    for skill, count in counts.most_common(top):
        examples: list[str] = []
        families: list[str] = []
        for j in jobs:
            if skill not in j.skills:
                continue
            if len(examples) < 3 and j.title not in examples:
                examples.append(j.title)
            if j.role_family not in families:
                families.append(j.role_family)
        result.append({"skill": skill, "count": count, "share": count / total if total else 0.0,
                       "example_titles": examples, "role_families": families})
    return result


def roles(session, city: str, days: int = 14) -> list[dict]:  # noqa: ANN001
    since = utcnow() - timedelta(days=days)
    jobs = repo.market_jobs_scope(session, city=city, since=since)
    by_family: dict[str, list[MarketJob]] = defaultdict(list)
    for j in jobs:
        by_family[j.role_family].append(j)
    result = []
    for family, fjobs in sorted(by_family.items(), key=lambda kv: -len(kv[1])):
        count = len(fjobs)
        flexible = sum(1 for j in fjobs if j.work_type in FLEXIBLE_WORK_TYPES)
        detailed = [j for j in fjobs if j.details_fetched]
        top_skills = [s for s, _ in Counter(s for j in detailed for s in j.skills).most_common(8)]
        result.append({"role_family": family, "count": count,
                       "flexible_share": flexible / count if count else 0.0, "top_skills": top_skills})
    return result


def trends(session, city: str, skills: list[str], weeks: int = 8) -> list[dict]:  # noqa: ANN001
    since = utcnow() - timedelta(weeks=weeks)
    snapshots = repo.market_snapshots_scope(session, city=city, since=since)
    points = []
    for snap in snapshots:
        denom = snap.detailed_count
        points.append({
            "date": snap.date,
            "shares": {sk: (snap.skill_counts.get(sk, 0) / denom if denom else 0.0) for sk in skills},
        })
    return points


HEAD_TO_HEAD_PAIRS: list[tuple[str, str]] = [("Java", "C#"), ("TypeScript", "JavaScript")]


def head_to_head_lines(adelaide_shares: dict, best_city: str, best_shares: dict) -> list[str]:
    lines = []
    for a, b in HEAD_TO_HEAD_PAIRS:
        lines.append(
            f"{a} vs {b}: Adelaide {adelaide_shares.get(a, 0) * 100:.0f}%/"
            f"{adelaide_shares.get(b, 0) * 100:.0f}% - {best_city.capitalize()} "
            f"{best_shares.get(a, 0) * 100:.0f}%/{best_shares.get(b, 0) * 100:.0f}%"
        )
    return lines
