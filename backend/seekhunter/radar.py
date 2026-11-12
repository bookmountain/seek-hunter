"""Company Radar: poll employers' own ATS feeds every 30 minutes so their ads show up before (or
without) SEEK/Jora/LinkedIn/Indeed, and take changedetection.io diffs for careers pages that have
no API. New radar jobs go through the same ingest -> evaluate -> instant-alert path as the crawl.
"""

import hashlib
import logging
import random
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser
from sqlmodel import Session, col, select

from seekhunter import repo
from seekhunter.domain import JobData, company_key, is_agency
from seekhunter.filters import is_on_topic, title_on_topic
from seekhunter.models import Job, JobEvaluation, RadarCompany, Run, utcnow
from seekhunter.pipeline import _apply_contacts, _evaluate, ingest, send_instant_alerts
from seekhunter.sources.ats import POLLED_ATS, ATSError, is_australian
from seekhunter.sources.ats.base import RADAR_SOURCE
from seekhunter.sources.ats.detect import Detection, detect_ats

log = logging.getLogger(__name__)

IGNORED_CAP = 500
CITY_LOCATIONS = {"adelaide": "Adelaide SA", "melbourne": "Melbourne VIC", "sydney": "Sydney NSW",
                  "perth": "Perth WA", "brisbane": "Brisbane QLD"}


# ---------------------------------------------------------------------------- companies


def get_company_by_key(session: Session, key: str) -> RadarCompany | None:
    return session.exec(select(RadarCompany).where(RadarCompany.company_key == key)).first()


def list_companies(session: Session, enabled_only: bool = False) -> list[RadarCompany]:
    stmt = select(RadarCompany).order_by(col(RadarCompany.name))
    if enabled_only:
        stmt = stmt.where(RadarCompany.enabled == True)  # noqa: E712
    return list(session.exec(stmt).all())


def upsert_company(session: Session, name: str, detection: Detection | None, *, source: str,
                   city: str | None = None, enabled: bool | None = None) -> RadarCompany:
    key = company_key(name)
    row = get_company_by_key(session, key) or RadarCompany(name=name.strip(), company_key=key, source=source)
    if detection is not None:
        row.ats, row.ats_token = detection.ats, detection.token
        row.careers_url = detection.careers_url or row.careers_url
    row.city = row.city or city
    if enabled is not None:
        row.enabled = enabled
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def add_company(session: Session, name: str, careers_url: str | None, http, clients: dict,  # noqa: ANN001
                city: str | None = None) -> RadarCompany:
    """Manual add: detect the ATS (careers URL first, then name guesses) and upsert."""
    detection = detect_ats(http, clients, name=name, careers_url=careers_url)
    row = upsert_company(session, name, detection, source="manual", city=city, enabled=True)
    if detection is None:
        row.last_error = "no ATS found; add a careers URL"
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def seed_candidates(session: Session, settings, now: datetime) -> list[tuple[str, str | None, int]]:  # noqa: ANN001
    """Direct employers (no agency keyword) with at least one on-topic job first seen within
    `radar_seed_days`, not yet on the radar: `[(display name, most common city, on-topic jobs)]`,
    most active first."""
    since = now - timedelta(days=settings.radar_seed_days)
    rows = session.exec(
        select(Job.company, Job.city, JobEvaluation.reasons)
        .join(JobEvaluation, JobEvaluation.job_id == Job.id)
        .where(Job.first_seen_at >= since, Job.source != RADAR_SOURCE)
    ).all()
    known = {c.company_key for c in list_companies(session)}
    names: dict[str, Counter] = {}
    cities: dict[str, Counter] = {}
    counts: Counter = Counter()
    for company, city, reasons in rows:
        key = company_key(company)
        if not key or key in known or is_agency(company, settings.agency_keywords):
            continue
        if "off_topic" in (reasons or []):
            continue
        counts[key] += 1
        names.setdefault(key, Counter())[company.strip()] += 1
        if city:
            cities.setdefault(key, Counter())[city] += 1
    return [
        (names[key].most_common(1)[0][0], cities[key].most_common(1)[0][0] if key in cities else None, n)
        for key, n in counts.most_common()
    ]


def seed_companies(session: Session, settings, http, clients: dict,  # noqa: ANN001
                   now: datetime | None = None, limit: int | None = None) -> dict:
    """Auto-seed: probe up to `radar_seed_max_probe` new direct employers. A found board is added
    enabled (source "auto"); a miss is still recorded (disabled, ats "other", no URL) so it isn't
    re-probed every seed run — add a careers URL later to have it watched."""
    now = now or utcnow()
    limit = settings.radar_seed_max_probe if limit is None else limit
    found = missed = 0
    added: list[str] = []
    for name, city, _ in seed_candidates(session, settings, now)[:limit]:
        try:
            detection = detect_ats(http, clients, name=name)
        except Exception as e:  # noqa: BLE001  one bad probe mustn't stop the seed run
            log.warning("radar seed: detection failed for %s: %s", name, e)
            detection = None
        if detection is not None and detection.ats in POLLED_ATS:
            upsert_company(session, name, detection, source="auto", city=city, enabled=True)
            found += 1
            added.append(f"{name} ({detection.ats}:{detection.token})")
        else:
            row = upsert_company(session, name, None, source="auto", city=city, enabled=False)
            row.last_error = "no ATS board found by name"
            session.add(row)
            session.commit()
            missed += 1
    return {"probed": found + missed, "found": found, "missed": missed, "added": added}


# ---------------------------------------------------------------------------- polling


class _Passthrough:
    """ingest() fetches details through `source.details`; radar jobs already have theirs."""

    def details(self, job: JobData) -> JobData:
        return job


def _ignore(company: RadarCompany, external_id: str) -> None:
    ids = [i for i in (company.ignored_ids or []) if i != external_id]
    company.ignored_ids = [*ids, external_id][-IGNORED_CAP:]


def _keep(data: JobData, settings) -> bool:  # noqa: ANN001
    return is_australian(data.location) and is_on_topic(data, settings)


def poll_company(session: Session, company: RadarCompany, clients: dict, settings,  # noqa: ANN001
                 st: dict) -> list[Job]:
    """One company's feed -> new, on-topic, Australian radar jobs (ingested). Raises on a feed
    error; the caller records it on the company."""
    client = clients[company.ats]
    listings = client.list_jobs(company)
    existing = set(session.exec(select(Job.external_id).where(
        Job.source == RADAR_SOURCE, col(Job.external_id).in_([d.external_id for d in listings]))).all())
    ignored = set(company.ignored_ids or [])
    new_jobs: list[Job] = []
    for data in listings:
        st["found"] += 1
        if data.external_id in existing:
            repo.upsert_job(session, data)  # bumps last_seen_at
            continue
        if data.external_id in ignored:
            continue
        # Cheap pre-checks before a detail fetch: a known non-AU location, or an off-topic title
        # when there's no description to judge by yet.
        location_known = bool(data.description_html) or company.ats != "workday"
        if data.location and location_known and not is_australian(data.location):
            _ignore(company, data.external_id)
            continue
        if not data.description_html and not title_on_topic(data.title, settings):
            _ignore(company, data.external_id)
            continue
        if not data.description_html:
            try:
                data = client.details(data)
            except Exception as e:  # noqa: BLE001  try again next poll
                log.warning("radar details failed for %s %s: %s", company.name, data.external_id, e)
                continue
        if not _keep(data, settings):
            _ignore(company, data.external_id)
            continue
        job = ingest(session, RADAR_SOURCE, _Passthrough(), data, None, st)
        if job is not None:
            new_jobs.append(job)
    company.last_job_count = len(listings)
    return new_jobs


class PageDetails:
    """Fills in a webhook-created radar job from its own ad page (best effort: main/article/body
    text, scripts and navigation stripped)."""

    def __init__(self, http) -> None:  # noqa: ANN001
        self.http = http

    def details(self, job: JobData) -> JobData:
        resp = self.http.get(job.url)
        if getattr(resp, "status_code", 200) != 200:
            return job
        tree = LexborHTMLParser(resp.text)
        for node in tree.css("script, style, nav, header, footer, noscript, form"):
            node.decompose()
        main = tree.css_first("main") or tree.css_first("article") or tree.body
        html = main.html if main else ""
        return replace(job, description_html=html or job.description_html)


def _fill_pending_details(session: Session, http, careers_urls: set[str], limit: int = 20) -> int:  # noqa: ANN001
    """Webhook jobs flagged `needs_details`: fetch the ad page when the link is the ad itself
    (not just the careers page the diff came from), then clear the flag and re-evaluate."""
    done = 0
    pending = session.exec(select(Job).where(Job.source == RADAR_SOURCE, Job.needs_details == True)  # noqa: E712
                           .order_by(col(Job.id)).limit(limit)).all()
    fetcher = PageDetails(http)
    for job in pending:
        if _norm_url(job.url) not in careers_urls:
            try:
                data = fetcher.details(repo.to_jobdata(job))
                repo.update_job_details(session, job, data)
                _apply_contacts(session, job)
            except Exception as e:  # noqa: BLE001  keep the minimal job; don't retry forever
                log.warning("radar page details failed for job %s: %s", job.id, e)
        job.needs_details = False
        session.add(job)
        session.commit()
        repo.delete_evaluation(session, job.id)
        done += 1
    return done


@dataclass
class RadarReport:
    run_id: int | None = None
    companies: int = 0
    errors: int = 0
    new_jobs: int = 0
    alerted: int = 0
    details_filled: int = 0
    status: dict = field(default_factory=dict)


def run_radar(session: Session, clients: dict, llm, notifier, profile, public_url: str,  # noqa: ANN001
              http=None, company_ids: list[int] | None = None, poll: bool = True,  # noqa: ANN001
              dry_run: bool = False, sleep: Callable[[float], None] = time.sleep) -> RadarReport:
    """Polls enabled API-backed companies (or just `company_ids`), fills in webhook jobs still
    needing details, scores everything new/unevaluated, and sends instant alerts. Per-company
    errors are recorded on the company and never stop the run."""
    settings = repo.load_settings(session)
    report = RadarReport()
    run = Run(kind="radar")
    session.add(run)
    session.commit()
    session.refresh(run)
    new_jobs: list[Job] = []
    try:
        if poll and (settings.radar_enabled or company_ids):
            companies = [c for c in list_companies(session) if c.ats in POLLED_ATS and (
                c.id in company_ids if company_ids else c.enabled)]
            for i, company in enumerate(companies):
                if i:
                    sleep(random.uniform(1.0, 2.0))
                st = {"found": 0, "new": 0}
                try:
                    new_jobs.extend(poll_company(session, company, clients, settings, st))
                    company.last_error = None
                except Exception as e:  # noqa: BLE001  isolate per-company failures
                    session.rollback()
                    report.errors += 1
                    company.last_error = (f"{type(e).__name__}: {e}" if not isinstance(e, ATSError)
                                          else str(e))[:300]
                    log.warning("radar %s (%s) failed: %s", company.name, company.ats, e)
                company.last_checked_at = utcnow()
                session.add(company)
                session.commit()
                report.companies += 1
                report.status[company.name] = {**st, "error": company.last_error}
        if http is not None:
            careers = {_norm_url(c.careers_url) for c in list_companies(session) if c.careers_url}
            report.details_filled = _fill_pending_details(session, http, careers)
        seen = {j.id for j in new_jobs}
        recovered = [j for j in repo.unevaluated_jobs(session) if j.id not in seen]
        run.llm_provider = _evaluate(session, new_jobs + recovered, profile, settings, llm)
        alerted = send_instant_alerts(session, new_jobs + recovered, settings, notifier, public_url,
                                      utcnow(), dry_run=dry_run)
        report.new_jobs, report.alerted = len(new_jobs), len(alerted)
        run.new_jobs, run.notified = len(new_jobs), len(alerted)
        run.source_status = {"radar": {"status": "ok" if not report.errors else "degraded",
                                       "companies": report.companies, "errors": report.errors,
                                       "new": len(new_jobs), "alerted": len(alerted)}}
    except Exception as e:
        session.rollback()
        run.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        run.finished_at = utcnow()
        session.add(run)
        session.commit()
        report.run_id = run.id
    return report


# ---------------------------------------------------------------------------- changedetection.io


def _norm_url(url: str | None) -> str:
    u = (url or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = u.removeprefix("www.")
    return u.split("#")[0].rstrip("/")


def match_company_by_url(session: Session, url: str) -> RadarCompany | None:
    """The radar company whose careers URL is this watch URL (exact after normalising, else the
    longest careers URL that's a prefix of it, else the same host)."""
    target = _norm_url(url)
    if not target:
        return None
    rows = [c for c in list_companies(session) if c.careers_url]
    exact = [c for c in rows if _norm_url(c.careers_url) == target]
    if exact:
        return exact[0]
    prefixed = sorted((c for c in rows if target.startswith(_norm_url(c.careers_url))),
                      key=lambda c: len(_norm_url(c.careers_url)), reverse=True)
    if prefixed:
        return prefixed[0]
    host = urlsplit(f"//{target}").hostname
    same_host = [c for c in rows if urlsplit(f"//{_norm_url(c.careers_url)}").hostname == host]
    return same_host[0] if len(same_host) == 1 else None


_WATCH_URL = re.compile(r"^\s*watch_url\s*[:=]\s*(\S+)", re.I | re.M)
_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_DIFF_PREFIX = re.compile(r"^\s*\((added|into|changed)\)\s*", re.I)
_ROLE_NOUN = re.compile(
    r"\b(engineer|developer|programmer|analyst|architect|administrator|admin|technician|specialist|"
    r"consultant|lead|manager|officer|designer|tester|scientist|support|intern|graduate|owner|"
    r"master|coordinator|devops|sre)s?\b", re.I)


@dataclass
class WebhookPayload:
    url: str | None
    text: str


def parse_changedetection(payload: dict) -> WebhookPayload:
    """Accepts changedetection.io's apprise `json://` body ({"title","message","type"}) with our
    template (see deploy/changedetection/sync_watches.py), or a flat JSON with watch_url/url and
    diff_added/diff/current_snapshot."""
    payload = payload or {}
    text = ""
    for key in ("diff_added", "diff", "current_snapshot", "message", "body"):
        if isinstance(payload.get(key), str) and payload[key].strip():
            text = payload[key]
            break
    url = payload.get("watch_url") or payload.get("url")
    if not url:
        m = _WATCH_URL.search(text) or _WATCH_URL.search(payload.get("title") or "")
        url = m.group(1) if m else None
    if not url:
        m = _URL.search(payload.get("title") or "") or _URL.search(text)
        url = m.group(0) if m else None
    return WebhookPayload(url=url, text=text)


def extract_roles(text: str, settings, base_url: str | None = None) -> list[tuple[str, str | None]]:  # noqa: ANN001
    """Role-like lines in a careers-page diff: `[(title, link or None)]`. A line counts when it's
    short, reads like a job title (a role noun) and is IT/software (`it_title_patterns`).
    "(removed)" lines are skipped."""
    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("(removed)") or _WATCH_URL.match(line):
            continue
        line = _DIFF_PREFIX.sub("", line).strip(" -•*|·\t")
        link_m = _URL.search(line)
        link = link_m.group(0).rstrip(".,;") if link_m else None
        title = _URL.sub("", line)
        title = re.sub(r"\[([^\]]*)\]\(\s*\)", r"\1", title)  # markdown link left without its URL
        title = re.sub(r"\s+", " ", title).strip(" -–—|:·()[]")
        if not (5 <= len(title) <= 120) or len(title.split()) > 14 or title.endswith((".", "?", "!")):
            continue
        if base_url and _norm_url(link) == _norm_url(base_url):
            link = None
        if not _ROLE_NOUN.search(title) or not title_on_topic(title, settings):
            continue
        if title.lower() in seen:
            continue
        seen.add(title.lower())
        out.append((title, link))
    return out


def ingest_webhook(session: Session, company: RadarCompany, roles: list[tuple[str, str | None]],
                   watch_url: str) -> list[Job]:
    """Creates minimal radar jobs (title, company, link; `needs_details`) for the diff's roles.
    Evaluation and alerts happen in the follow-up `seekhunter radar --pending` run."""
    created: list[Job] = []
    location = CITY_LOCATIONS.get(company.city or "", "")
    for title, link in roles:
        url = link or company.careers_url or watch_url
        ext = "cd:" + hashlib.sha1(f"{company.id}|{link or title.lower()}".encode()).hexdigest()[:16]
        data = JobData(source=RADAR_SOURCE, external_id=ext, title=title, company=company.name,
                       location=location, work_type="unknown", url=url, listed_at=utcnow())
        st: dict = {}
        job = ingest(session, RADAR_SOURCE, _Passthrough(), data, None, st, fetch_details=False)
        if job is None:
            continue
        job.needs_details = True
        session.add(job)
        session.commit()
        created.append(job)
    company.last_checked_at = utcnow()
    session.add(company)
    session.commit()
    return created
