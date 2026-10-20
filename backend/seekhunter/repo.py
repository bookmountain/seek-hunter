import re
from datetime import datetime, timedelta

from sqlalchemy import case, func, or_
from sqlmodel import Session, col, select

from seekhunter.domain import (
    JobData,
    company_key,
    dedupe_key,
    derive_city,
    html_to_text,
    infer_work_type,
    normalize_location,
)
from seekhunter.models import (
    Application,
    ApplicationEvent,
    Contact,
    ContactJob,
    Interaction,
    Job,
    JobEvaluation,
    MarketJob,
    MarketSnapshot,
    Outbox,
    Run,
    SearchProfile,
    SettingsRow,
    Tailoring,
    utcnow,
)
from seekhunter.settings_model import AppSettings

DEFAULT_KEYWORDS = [
    "software engineer", "developer", "full stack", "frontend", "AI engineer", "graduate developer",
]
OTHER_CITY_KEYWORDS = ["software engineer", "developer", "full stack", "IT support"]
OTHER_CITY_LOCATIONS = {
    "Melbourne": "All Melbourne VIC",
    "Sydney": "All Sydney NSW",
    "Perth": "All Perth WA",
}


def upsert_job(session: Session, data: JobData, profile_location: str | None = None) -> tuple[Job, bool]:
    """Inserts a new job, or returns the existing one unchanged (first finder wins — including the
    `city`, derived from `profile_location` when it's a recognised search-profile location, else
    parsed from the job's own `location` text; see `domain.derive_city`)."""
    existing = session.exec(
        select(Job).where(Job.source == data.source, Job.external_id == data.external_id)
    ).first()
    if existing:
        existing.last_seen_at = utcnow()
        session.add(existing)
        session.commit()
        return existing, False
    job = Job(
        source=data.source, external_id=data.external_id, title=data.title, company=data.company,
        location=normalize_location(data.location), city=derive_city(profile_location, data.location),
        work_type=data.work_type, salary_label=data.salary_label,
        listed_at=data.listed_at, url=data.url, teaser=data.teaser, description_html=data.description_html,
        dedupe_key=dedupe_key(data.title, data.company),
        last_seen_at=utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job, True


_MASKED_EMAIL = re.compile(r"(\*{3,})@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
_EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def unmask_emails(session: Session, job: Job) -> bool:
    """Jora hides addresses in ad text ("**************@talentweb.com.au"). Restore each one when
    exactly one address at that domain with the same local-part length is known from another ad
    (typically the same ad on SEEK). Also fills an empty contact_email. Returns True on a change."""
    html = job.description_html or ""
    masks = _MASKED_EMAIL.findall(html)
    if not masks:
        return False
    changed = False
    for stars, domain in dict.fromkeys(masks):
        known: set[str] = set()
        others = session.exec(select(Job.contact_email, Job.description_html).where(
            Job.id != job.id, or_(col(Job.contact_email).ilike(f"%@{domain}"),
                                  col(Job.description_html).contains(f"@{domain}")))).all()
        for email, body in others:
            for e in ([email] if email else []) + _EMAIL.findall(body or ""):
                local, _, dom = e.rpartition("@")
                if dom.lower() == domain.lower() and len(local) == len(stars) and "*" not in local:
                    known.add(e.lower())
        if len(known) == 1:
            found = known.pop()
            html = html.replace(f"{stars}@{domain}", found)
            if not job.contact_email:
                job.contact_email = found
            changed = True
    if changed:
        job.description_html = html
        session.add(job)
        session.commit()
    return changed


def update_job_details(session: Session, job: Job, data: JobData) -> None:
    job.description_html = data.description_html or job.description_html
    if job.work_type == "unknown" and data.work_type != "unknown":
        job.work_type = data.work_type
    if job.work_type == "unknown":  # board didn't label it (common on Jora): infer from the ad text
        job.work_type = infer_work_type(html_to_text(job.description_html) or job.teaser)
    job.contact_phone = job.contact_phone or data.contact_phone
    job.contact_email = job.contact_email or data.contact_email
    session.add(job)
    session.commit()
    unmask_emails(session, job)


def jobs_missing_details(session: Session, source: str, since: datetime, limit: int) -> list[Job]:
    """Canonical, non-hidden jobs from `source` seen since `since` whose detail page was never
    fetched (empty description), newest first."""
    return list(session.exec(
        select(Job).where(Job.source == source, Job.first_seen_at >= since, Job.description_html == "",
                          col(Job.canonical_job_id).is_(None), Job.status != "hidden")
        .order_by(col(Job.first_seen_at).desc()).limit(limit)).all())


def backfill_job_fields(session: Session, job: Job) -> None:
    """Fill fields that older crawls left blank/raw: infer an unknown work type from the ad text and
    normalise LinkedIn-style locations ('Adelaide, South Australia, Australia' -> 'Adelaide SA')."""
    changed = False
    if job.work_type == "unknown":
        inferred = infer_work_type(html_to_text(job.description_html) or job.teaser)
        if inferred != "unknown":
            job.work_type, changed = inferred, True
    normalized = normalize_location(job.location)
    if normalized != job.location:
        job.location, changed = normalized, True
    if changed:
        session.add(job)
        session.commit()
    unmask_emails(session, job)


def to_jobdata(job: Job) -> JobData:
    return JobData(source=job.source, external_id=job.external_id, title=job.title, company=job.company,
                   location=job.location, work_type=job.work_type, url=job.url, salary_label=job.salary_label,
                   listed_at=job.listed_at, teaser=job.teaser, description_html=job.description_html,
                   contact_phone=job.contact_phone, contact_email=job.contact_email,
                   applicant_count=job.applicant_count, applicant_volume=job.applicant_volume,
                   resume_pct=job.resume_pct, cover_letter_pct=job.cover_letter_pct)


def set_contacts(session: Session, job: Job, *, name: str | None = None, phone: str | None = None,
                 email: str | None = None, linkedin: str | None = None) -> None:
    if name is not None:
        job.contact_name = name
    if phone is not None:
        job.contact_phone = phone
    if email is not None:
        job.contact_email = email
    if linkedin is not None:
        job.contact_linkedin = linkedin
    session.add(job)
    session.commit()


def set_insights(session: Session, job: Job, data: dict | None, checked_at: datetime) -> None:
    """Applies a SEEK insights refresh. `data` may be `None` (the lookup failed, e.g. a GraphQL
    error) or an empty dict (SEEK has no insights published for this ad); either way
    `insights_checked_at` is still bumped so the job isn't retried again immediately. Present keys
    overwrite the matching field; absent keys are left untouched."""
    if data:
        job.applicant_count = data.get("applicant_count", job.applicant_count)
        job.applicant_volume = data.get("applicant_volume", job.applicant_volume)
        job.resume_pct = data.get("resume_pct", job.resume_pct)
        job.cover_letter_pct = data.get("cover_letter_pct", job.cover_letter_pct)
    job.insights_checked_at = checked_at
    session.add(job)
    session.commit()


def jobs_needing_insights(session: Session, now: datetime, limit: int,
                          notify_cities: list[str] | None = None) -> list[Job]:
    """SEEK jobs eligible for an insights refresh: canonical (not a duplicate), not hidden, first
    seen within the last 7 days, and not checked within the last 3 hours. When `notify_cities` is
    given, jobs in those cities sort first (they're the ones that actually reach Telegram); within
    each group, never-checked jobs (`insights_checked_at IS NULL`) sort first, then the longest-
    stale ones."""
    cutoff = now - timedelta(hours=3)
    window = now - timedelta(days=7)
    stmt = (
        select(Job)
        .where(Job.source == "seek", col(Job.canonical_job_id).is_(None), Job.status != "hidden",
               Job.first_seen_at >= window,
               or_(col(Job.insights_checked_at).is_(None), Job.insights_checked_at < cutoff))
    )
    order_cols = []
    if notify_cities:
        order_cols.append(case((col(Job.city).in_(notify_cities), 0), else_=1))
    order_cols.append(col(Job.insights_checked_at).asc())
    stmt = stmt.order_by(*order_cols).limit(limit)
    return list(session.exec(stmt).all())


def find_duplicate(session: Session, job: Job) -> int | None:
    if job.dedupe_key.startswith("|") or job.dedupe_key.endswith("|"):
        return None
    other = session.exec(
        select(Job).where(Job.dedupe_key == job.dedupe_key, Job.id != job.id, Job.source != job.source,
                          col(Job.canonical_job_id).is_(None))
        .order_by(col(Job.id))
    ).first()
    return other.id if other else None


def save_evaluation(session: Session, job_id: int, **fields) -> JobEvaluation:
    ev = session.exec(select(JobEvaluation).where(JobEvaluation.job_id == job_id)).first() or JobEvaluation(
        job_id=job_id)
    for k, v in fields.items():
        setattr(ev, k, v)
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev


def unevaluated_jobs(session: Session) -> list[Job]:
    """Jobs with no evaluation row yet (e.g. left behind by a crashed earlier run)."""
    stmt = (
        select(Job).join(JobEvaluation, JobEvaluation.job_id == Job.id, isouter=True)
        .where(col(JobEvaluation.id).is_(None), col(Job.canonical_job_id).is_(None))
    )
    return list(session.exec(stmt).all())


def jobs_since(session: Session, since: datetime) -> list[Job]:
    return list(session.exec(
        select(Job).where(Job.first_seen_at >= since, col(Job.canonical_job_id).is_(None))).all())


def get_evaluation(session: Session, job_id: int) -> JobEvaluation | None:
    return session.exec(select(JobEvaluation).where(JobEvaluation.job_id == job_id)).first()


def delete_evaluation(session: Session, job_id: int) -> None:
    ev = get_evaluation(session, job_id)
    if ev:
        session.delete(ev)
        session.commit()


def _open_or_kept():
    """Closed ads drop out of the active list, except ones Book saved or applied to."""
    return or_(col(Job.closed_at).is_(None), col(Job.status).in_(["saved", "applied"]))


def _active_clause():
    return (
        col(Job.canonical_job_id).is_(None),
        Job.status != "hidden",
        col(Job.closed_at).is_(None),
        or_(JobEvaluation.excluded == False, Job.force_include == True),  # noqa: E712
    )


def notification_candidates(session: Session, now: datetime,
                            notify_cities: list[str] | None = None) -> list[tuple[Job, JobEvaluation]]:
    """Jobs eligible for a Telegram digest. `notify_cities`, when given, restricts this to jobs in
    those cities (e.g. settings.notify_cities, Adelaide-only by default) — jobs from other cities
    are still crawled/scored/notified_at never set, so enabling a city later only notifies jobs
    seen in the last 48h, not a backlog."""
    stmt = (
        select(Job, JobEvaluation).join(JobEvaluation, JobEvaluation.job_id == Job.id)
        .where(*_active_clause(), col(Job.notified_at).is_(None),
               Job.first_seen_at >= now - timedelta(hours=48))
    )
    if notify_cities is not None:
        stmt = stmt.where(col(Job.city).in_(notify_cities))
    stmt = stmt.order_by(col(JobEvaluation.final_score).desc(), col(Job.first_seen_at).desc())
    return list(session.exec(stmt).all())


NOTIFICATIONS_READ_FALLBACK = timedelta(hours=24)


def notifications_read_at(session: Session, now: datetime) -> tuple[datetime | None, datetime]:
    """`(stored, effective)`: the raw server-side "last read" marker (`None` before it's ever been
    set) and the cutoff actually used to decide what's unread — `stored`, or `now` minus
    `NOTIFICATIONS_READ_FALLBACK` when nothing has been read yet."""
    stored = load_settings(session).notifications_read_at
    return stored, stored or (now - NOTIFICATIONS_READ_FALLBACK)


def mark_notifications_read(session: Session, when: datetime) -> None:
    settings = load_settings(session)
    settings.notifications_read_at = when
    save_settings(session, settings)


def unread_job_items(session: Session, since: datetime) -> list[tuple[Job, JobEvaluation]]:
    """Active (not excluded/hidden/duplicate) jobs first seen after `since`, across all cities,
    newest first — the "job" items in the in-app notification feed."""
    stmt = (
        select(Job, JobEvaluation).join(JobEvaluation, JobEvaluation.job_id == Job.id)
        .where(*_active_clause(), Job.first_seen_at > since)
        .order_by(col(Job.first_seen_at).desc())
    )
    return list(session.exec(stmt).all())


def unread_tailoring_items(session: Session, since: datetime) -> list[Tailoring]:
    """Tailorings that finished (done or failed) after `since`, newest first — the "tailoring"
    items in the in-app notification feed."""
    stmt = (
        select(Tailoring)
        .where(col(Tailoring.status).in_(["done", "failed"]), col(Tailoring.finished_at).is_not(None),
               Tailoring.finished_at > since)
        .order_by(col(Tailoring.finished_at).desc())
    )
    return list(session.exec(stmt).all())


def mark_notified(session: Session, job_ids: list[int], when: datetime) -> None:
    for job in session.exec(select(Job).where(col(Job.id).in_(job_ids))).all():
        job.notified_at = when
        session.add(job)
    session.commit()


def list_jobs(session: Session, view: str = "active", status: str | None = None, work_type: str | None = None,
              source: str | None = None, q: str | None = None, since: datetime | None = None,
              city: str | None = None, cities: list[str] | None = None, limit: int = 200,
              offset: int = 0) -> list[tuple[Job, JobEvaluation]]:
    stmt = select(Job, JobEvaluation).join(JobEvaluation, JobEvaluation.job_id == Job.id)
    if view == "excluded":
        stmt = stmt.where(JobEvaluation.excluded == True, Job.force_include == False)  # noqa: E712
        stmt = stmt.order_by(col(Job.first_seen_at).desc())
    else:
        stmt = stmt.where(col(Job.canonical_job_id).is_(None),
                          or_(JobEvaluation.excluded == False, Job.force_include == True))  # noqa: E712
        if status == "closed":
            stmt = stmt.where(col(Job.closed_at).is_not(None))
        elif status:
            stmt = stmt.where(Job.status == status, _open_or_kept())
        else:
            stmt = stmt.where(Job.status != "hidden", _open_or_kept())
        stmt = stmt.order_by(col(JobEvaluation.final_score).desc(), col(Job.first_seen_at).desc())
    if work_type:
        stmt = stmt.where(Job.work_type == work_type)
    if source:
        stmt = stmt.where(Job.source == source)
    if since:
        stmt = stmt.where(Job.first_seen_at >= since)
    if city:
        stmt = stmt.where(Job.city == city)
    if cities is not None:
        stmt = stmt.where(col(Job.city).in_(cities))
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        stmt = stmt.where(or_(
            col(Job.title).ilike(like, escape="\\"), col(Job.company).ilike(like, escape="\\")))
    return list(session.exec(stmt.offset(offset).limit(limit)).all())


def jobs_to_check_open(session: Session, now: datetime, limit: int,
                       sources: list[str] | None = None) -> list[Job]:
    """Listed jobs whose ad should be re-checked for closure: ones a search hasn't returned for a day
    first, then the longest-unchecked. Ads seen for under 12h are skipped (they're clearly live)."""
    stmt = select(Job).where(col(Job.canonical_job_id).is_(None), col(Job.closed_at).is_(None),
                             Job.status != "hidden", Job.first_seen_at <= now - timedelta(hours=12))
    if sources is not None:
        stmt = stmt.where(col(Job.source).in_(sources))
    unseen = or_(col(Job.last_seen_at).is_(None), col(Job.last_seen_at) < now - timedelta(hours=24))
    stmt = stmt.order_by(case((unseen, 0), else_=1), col(Job.open_checked_at).is_not(None),
                         col(Job.open_checked_at), col(Job.first_seen_at))
    return list(session.exec(stmt.limit(limit)).all())


def count_excluded_since(session: Session, since: datetime, cities: list[str] | None = None) -> int:
    stmt = (
        select(func.count()).select_from(Job).join(JobEvaluation, JobEvaluation.job_id == Job.id)
        .where(JobEvaluation.excluded == True, Job.force_include == False,  # noqa: E712
               Job.first_seen_at >= since)
    )
    if cities is not None:
        stmt = stmt.where(col(Job.city).in_(cities))
    return session.exec(stmt).one()


def job_city_counts(session: Session, view: str = "active") -> list[tuple[str | None, int]]:
    """`[(city, count)]` for the given jobs-list `view`, mirroring `list_jobs`'s filtering — used by
    the Jobs page location filter to show counts per city."""
    stmt = select(Job.city, func.count()).select_from(Job).join(JobEvaluation, JobEvaluation.job_id == Job.id)
    if view == "excluded":
        stmt = stmt.where(JobEvaluation.excluded == True, Job.force_include == False)  # noqa: E712
    else:
        stmt = stmt.where(col(Job.canonical_job_id).is_(None),
                          or_(JobEvaluation.excluded == False, Job.force_include == True),  # noqa: E712
                          Job.status != "hidden")
    stmt = stmt.group_by(Job.city)
    return list(session.exec(stmt).all())


def load_settings(session: Session) -> AppSettings:
    row = session.get(SettingsRow, 1)
    return AppSettings.model_validate(row.data) if row and row.data else AppSettings()


def save_settings(session: Session, settings: AppSettings) -> None:
    row = session.get(SettingsRow, 1) or SettingsRow(id=1)
    # mode="json" so NaiveDatetime fields (notifications_read_at) serialize to ISO strings rather
    # than raw datetime objects, which the sqlite JSON column can't store.
    row.data = settings.model_dump(mode="json")
    session.add(row)
    session.commit()


def list_search_profiles(session: Session, enabled_only: bool = False) -> list[SearchProfile]:
    stmt = select(SearchProfile).order_by(col(SearchProfile.id))
    if enabled_only:
        stmt = stmt.where(SearchProfile.enabled == True)  # noqa: E712
    return list(session.exec(stmt).all())


def ensure_seed(session: Session) -> None:
    if session.get(SettingsRow, 1) is None:
        save_settings(session, AppSettings())
    if not list_search_profiles(session):
        for kw in DEFAULT_KEYWORDS:
            session.add(SearchProfile(name=f"Adelaide · {kw}", keywords=kw, location="All Adelaide SA"))
        session.commit()
    _ensure_other_city_profiles(session)
    _ensure_linkedin_source(session)


def _ensure_other_city_profiles(session: Session) -> None:
    """Melbourne/Sydney/Perth search profiles for the multi-city jobs feed. Runs every time
    (startup and every CLI command), not just on a fresh database, so this also acts as the
    one-time migration for existing databases that were seeded before these cities existed.
    Idempotent by (keywords, location): re-running never duplicates a profile."""
    existing = {(p.keywords, p.location) for p in list_search_profiles(session)}
    for city_name, location in OTHER_CITY_LOCATIONS.items():
        for kw in OTHER_CITY_KEYWORDS:
            if (kw, location) in existing:
                continue
            session.add(SearchProfile(name=f"{city_name} · {kw}", keywords=kw, location=location,
                                      enabled=True))
    session.commit()


def _ensure_linkedin_source(session: Session) -> None:
    """Adds "linkedin" to every search profile's `sources` list that doesn't already have it — the
    migration for databases seeded before LinkedIn existed as a source. Runs every time (like
    `_ensure_other_city_profiles`); idempotent, since it's a no-op once every profile has it."""
    changed = False
    for p in list_search_profiles(session):
        if "linkedin" not in p.sources:
            p.sources = [*p.sources, "linkedin"]
            session.add(p)
            changed = True
    if changed:
        session.commit()


def recent_runs(session: Session, kind: str = "crawl", limit: int = 50) -> list[Run]:
    return list(session.exec(
        select(Run).where(Run.kind == kind).order_by(col(Run.started_at).desc()).limit(limit)).all())


def pending_outbox(session: Session) -> list[Outbox]:
    stmt = select(Outbox).where(col(Outbox.sent_at).is_(None), Outbox.attempts < 10).order_by(col(Outbox.id))
    return list(session.exec(stmt).all())


def upsert_market_job(session: Session, data: JobData, city: str, keyword: str, now: datetime, *,
                      role_family: str, skills: list[str], salary_min_hourly: float | None,
                      salary_max_hourly: float | None) -> tuple[MarketJob, bool]:
    """Upserts into `market_jobs` (separate from `jobs`): a job already seen just gets
    `last_seen_at` bumped; a new one is inserted with the role family, extracted skills, and
    normalised hourly salary computed by the caller (`seekhunter.market`)."""
    existing = session.exec(
        select(MarketJob).where(MarketJob.source == data.source, MarketJob.external_id == data.external_id)
    ).first()
    if existing:
        existing.last_seen_at = now
        session.add(existing)
        session.commit()
        return existing, False
    job = MarketJob(
        source=data.source, external_id=data.external_id, city=city, keyword=keyword, title=data.title,
        company=data.company, work_type=data.work_type, salary_label=data.salary_label,
        salary_min_hourly=salary_min_hourly, salary_max_hourly=salary_max_hourly, listed_at=data.listed_at,
        role_family=role_family, skills=skills, details_fetched=False, first_seen_at=now, last_seen_at=now,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job, True


def apply_market_details(session: Session, job: MarketJob, skills: list[str]) -> None:
    job.skills = skills
    job.details_fetched = True
    session.add(job)
    session.commit()


def market_jobs_needing_details(session: Session, city: str, limit: int) -> list[MarketJob]:
    """Not-yet-detailed `market_jobs` for one city, newest first, capped at `limit`."""
    stmt = (
        select(MarketJob)
        .where(MarketJob.city == city, MarketJob.details_fetched == False)  # noqa: E712
        .order_by(col(MarketJob.first_seen_at).desc())
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def to_market_jobdata(job: MarketJob) -> JobData:
    return JobData(source=job.source, external_id=job.external_id, title=job.title, company=job.company,
                   location=job.city, work_type=job.work_type,
                   url=f"https://www.seek.com.au/job/{job.external_id}", salary_label=job.salary_label,
                   listed_at=job.listed_at)


def market_jobs_scope(session: Session, city: str | None = None, since: datetime | None = None,
                      role_family: str | None = None, detailed_only: bool = False) -> list[MarketJob]:
    stmt = select(MarketJob)
    if city:
        stmt = stmt.where(MarketJob.city == city)
    if since:
        stmt = stmt.where(MarketJob.last_seen_at >= since)
    if role_family:
        stmt = stmt.where(MarketJob.role_family == role_family)
    if detailed_only:
        stmt = stmt.where(MarketJob.details_fetched == True)  # noqa: E712
    return list(session.exec(stmt).all())


def save_market_snapshot(session: Session, city: str, date: datetime, stats: dict) -> MarketSnapshot:
    """Upserts the one `market_snapshots` row for (city, date) — re-running the market crawl on
    the same day replaces, rather than duplicates, today's snapshot."""
    existing = session.exec(
        select(MarketSnapshot).where(MarketSnapshot.city == city, MarketSnapshot.date == date)
    ).first()
    row = existing or MarketSnapshot(city=city, date=date)
    row.total = stats["total"]
    row.detailed_count = stats["detailed_count"]
    row.by_work_type = stats["by_work_type"]
    row.by_role_family = stats["by_role_family"]
    row.skill_counts = stats["skill_counts"]
    row.salary_percentiles = stats["salary_percentiles"]
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def market_snapshots_scope(session: Session, city: str,
                           since: datetime | None = None) -> list[MarketSnapshot]:
    stmt = select(MarketSnapshot).where(MarketSnapshot.city == city)
    if since:
        stmt = stmt.where(MarketSnapshot.date >= since)
    return list(session.exec(stmt.order_by(col(MarketSnapshot.date))).all())


TAILORING_STALE_AFTER = timedelta(minutes=30)


def create_tailoring(session: Session, job_id: int, send: bool = False) -> Tailoring:
    t = Tailoring(job_id=job_id, send_requested=send)
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def save_tailoring(session: Session, t: Tailoring) -> None:
    session.add(t)
    session.commit()
    session.refresh(t)


def list_tailorings(session: Session, job_id: int, limit: int = 20) -> list[Tailoring]:
    return list(session.exec(
        select(Tailoring).where(Tailoring.job_id == job_id)
        .order_by(col(Tailoring.created_at).desc(), col(Tailoring.id).desc()).limit(limit)).all())


def list_all_tailorings(session: Session, limit: int = 100) -> list[Tailoring]:
    return list(session.exec(
        select(Tailoring).order_by(col(Tailoring.created_at).desc(), col(Tailoring.id).desc()).limit(limit)
    ).all())


def active_tailoring(session: Session, job_id: int, now: datetime) -> Tailoring | None:
    """The job's queued/running tailoring, if any. Ones older than TAILORING_STALE_AFTER are assumed
    dead (worker crashed or was killed) and marked failed so a new one can start."""
    rows = session.exec(select(Tailoring).where(
        Tailoring.job_id == job_id, col(Tailoring.status).in_(["queued", "running"]))
        .order_by(col(Tailoring.id).desc())).all()
    active = None
    for t in rows:
        if t.created_at < now - TAILORING_STALE_AFTER:
            t.status, t.error, t.finished_at = "failed", "timed out (worker did not finish)", now
            session.add(t)
        elif active is None:
            active = t
    session.commit()
    return active


# ---------------------------------------------------------------------------- applications


def latest_done_tailoring(session: Session, job_id: int) -> Tailoring | None:
    return session.exec(
        select(Tailoring).where(Tailoring.job_id == job_id, Tailoring.status == "done")
        .order_by(col(Tailoring.created_at).desc(), col(Tailoring.id).desc())
    ).first()


def get_application_by_job(session: Session, job_id: int) -> Application | None:
    return session.exec(select(Application).where(Application.job_id == job_id)).first()


def create_application(session: Session, *, job_id: int | None, company: str, title: str,
                       url: str | None = None, location: str | None = None,
                       applied_at: datetime | None = None, tailoring_id: int | None = None,
                       stage: str = "applied", source: str = "seekhunter", notes: str = "") -> Application:
    now = utcnow()
    applied_at = applied_at or now
    app = Application(job_id=job_id, company=company, company_key=company_key(company), title=title, url=url,
                      location=location, applied_at=applied_at, tailoring_id=tailoring_id, stage=stage,
                      source=source, notes=notes, created_at=now, updated_at=now)
    session.add(app)
    session.commit()
    session.refresh(app)
    session.add(ApplicationEvent(application_id=app.id, kind="created", to_stage=stage, at=applied_at))
    session.commit()
    return app


def ensure_application_for_job(session: Session, job: Job, now: datetime | None = None) -> Application:
    """Idempotent: called when a job's status is set to `applied`. Reuses any existing application
    for this job rather than creating a duplicate."""
    existing = get_application_by_job(session, job.id)
    if existing:
        return existing
    tailoring = latest_done_tailoring(session, job.id)
    return create_application(
        session, job_id=job.id, company=job.company, title=job.title, url=job.url, location=job.location,
        applied_at=now or utcnow(), tailoring_id=tailoring.id if tailoring else None)


def update_application(session: Session, app: Application, *, stage: str | None = None,
                       notes: str | None = None, applied_at: datetime | None = None,
                       tailoring_id: int | None = None) -> Application:
    now = utcnow()
    if stage is not None and stage != app.stage:
        session.add(ApplicationEvent(application_id=app.id, kind="stage_changed", from_stage=app.stage,
                                     to_stage=stage, at=now))
        app.stage = stage
    if notes is not None:
        app.notes = notes
    if applied_at is not None:
        app.applied_at = applied_at
    if tailoring_id is not None:
        app.tailoring_id = tailoring_id
    app.updated_at = now
    session.add(app)
    session.commit()
    session.refresh(app)
    return app


def delete_application(session: Session, app: Application) -> None:
    for ev in session.exec(select(ApplicationEvent).where(ApplicationEvent.application_id == app.id)).all():
        session.delete(ev)
    for interaction in session.exec(
        select(Interaction).where(Interaction.application_id == app.id)
    ).all():
        interaction.application_id = None
        session.add(interaction)
    session.delete(app)
    session.commit()


def list_applications(session: Session, stage: str | None = None, q: str | None = None) -> list[Application]:
    stmt = select(Application)
    if stage:
        stmt = stmt.where(Application.stage == stage)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        stmt = stmt.where(or_(col(Application.title).ilike(like, escape="\\"),
                              col(Application.company).ilike(like, escape="\\")))
    return list(session.exec(stmt.order_by(col(Application.applied_at).desc())).all())


def applications_by_company_keys(session: Session, keys: set[str]) -> dict[str, list[Application]]:
    """Batch-loads applications grouped by `company_key`, newest first within each group — one query
    regardless of how many jobs/companies are being enriched (used by the jobs list endpoint)."""
    keys = {k for k in keys if k}
    if not keys:
        return {}
    rows = session.exec(
        select(Application).where(col(Application.company_key).in_(keys))
        .order_by(col(Application.applied_at).desc())
    ).all()
    out: dict[str, list[Application]] = {}
    for a in rows:
        out.setdefault(a.company_key, []).append(a)
    return out


def applications_by_job_ids(session: Session, job_ids: list[int]) -> dict[int, Application]:
    if not job_ids:
        return {}
    rows = session.exec(select(Application).where(col(Application.job_id).in_(job_ids))).all()
    return {a.job_id: a for a in rows}


def stage_counts(session: Session) -> dict[str, int]:
    rows = session.exec(select(Application.stage, func.count()).group_by(Application.stage)).all()
    return dict(rows)


def recent_applications(session: Session, since: datetime) -> list[Application]:
    return list(session.exec(
        select(Application).where(Application.applied_at >= since)
        .order_by(col(Application.applied_at).desc())).all())


def follow_ups_due(session: Session, now: datetime, days: int = 7) -> list[Application]:
    """Applications still in `applied` with no activity (event or interaction) in the last `days`
    days, oldest-applied first."""
    cutoff = now - timedelta(days=days)
    apps = session.exec(
        select(Application).where(Application.stage == "applied", Application.applied_at <= cutoff)
    ).all()
    due = []
    for a in apps:
        last_event = session.exec(
            select(ApplicationEvent).where(ApplicationEvent.application_id == a.id)
            .order_by(col(ApplicationEvent.at).desc())
        ).first()
        last_interaction = session.exec(
            select(Interaction).where(Interaction.application_id == a.id)
            .order_by(col(Interaction.at).desc())
        ).first()
        last_activity = max(
            (x.at for x in (last_event, last_interaction) if x is not None), default=a.applied_at)
        if last_activity <= cutoff:
            due.append(a)
    due.sort(key=lambda a: a.applied_at)
    return due


# ---------------------------------------------------------------------------- contacts


def upsert_contact(session: Session, *, name: str, company: str = "", role: str | None = None,
                   phone: str | None = None, email: str | None = None, linkedin: str | None = None,
                   notes: str | None = None) -> Contact:
    """Upserts matched by (lower(name), company_key): merges in any missing phone/email/linkedin/role
    rather than overwriting fields the existing contact already has."""
    now = utcnow()
    key = company_key(company)
    existing = session.exec(
        select(Contact).where(func.lower(Contact.name) == name.lower(), Contact.company_key == key)
    ).first()
    if existing:
        existing.phone = existing.phone or phone
        existing.email = existing.email or email
        existing.linkedin = existing.linkedin or linkedin
        existing.role = existing.role or role
        existing.company = existing.company or company
        if notes:
            existing.notes = notes
        existing.updated_at = now
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    contact = Contact(name=name, company=company, company_key=key, role=role, phone=phone, email=email,
                      linkedin=linkedin, notes=notes or "", created_at=now, updated_at=now)
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return contact


def find_contact(session: Session, name: str, company: str) -> Contact | None:
    return session.exec(
        select(Contact).where(func.lower(Contact.name) == name.lower(),
                              Contact.company_key == company_key(company))
    ).first()


def prune_uncontacted_contacts(session: Session) -> int:
    """Delete contacts with no logged interaction and no linked application (auto-added recruiters
    from ads that Book never actually contacted). Returns how many were removed."""
    removed = 0
    for contact in session.exec(select(Contact)).all():
        stats = contact_stats(session, contact.id)
        if stats["interaction_count"] == 0 and stats["application_count"] == 0:
            for link in session.exec(select(ContactJob).where(ContactJob.contact_id == contact.id)).all():
                session.delete(link)
            session.delete(contact)
            removed += 1
    session.commit()
    return removed


ACTIVITY_KINDS = ("call", "email", "linkedin_invite", "linkedin_accepted", "linkedin_message", "meeting")


def contact_activity_by_job_ids(session: Session, job_ids: list[int]) -> dict[int, list[str]]:
    """Interaction kinds logged with each job's linked contacts (notes excluded), in a fixed order."""
    if not job_ids:
        return {}
    rows = session.exec(
        select(ContactJob.job_id, Interaction.kind)
        .join(Interaction, Interaction.contact_id == ContactJob.contact_id)
        .where(col(ContactJob.job_id).in_(job_ids), col(Interaction.kind).in_(ACTIVITY_KINDS))
        .distinct()).all()
    kinds: dict[int, set[str]] = {}
    for job_id, kind in rows:
        kinds.setdefault(job_id, set()).add(kind)
    return {jid: [k for k in ACTIVITY_KINDS if k in ks] for jid, ks in kinds.items()}


def link_contact_job(session: Session, contact_id: int, job_id: int) -> None:
    existing = session.exec(
        select(ContactJob).where(ContactJob.contact_id == contact_id, ContactJob.job_id == job_id)
    ).first()
    if existing:
        return
    session.add(ContactJob(contact_id=contact_id, job_id=job_id))
    session.commit()


def list_contacts(session: Session, q: str | None = None) -> list[Contact]:
    stmt = select(Contact)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        stmt = stmt.where(or_(col(Contact.name).ilike(like, escape="\\"),
                              col(Contact.company).ilike(like, escape="\\")))
    return list(session.exec(stmt.order_by(col(Contact.name))).all())


def contact_stats(session: Session, contact_id: int) -> dict:
    interactions = session.exec(
        select(Interaction).where(Interaction.contact_id == contact_id)
        .order_by(col(Interaction.at).desc())
    ).all()
    job_ids = [cj.job_id for cj in session.exec(
        select(ContactJob).where(ContactJob.contact_id == contact_id)).all()]
    application_count = 0
    if job_ids:
        application_count = session.exec(
            select(func.count()).select_from(Application).where(col(Application.job_id).in_(job_ids))
        ).one()
    return {
        "last_interaction": interactions[0].at if interactions else None,
        "interaction_count": len(interactions),
        "job_count": len(job_ids),
        "application_count": application_count,
    }


def interactions_for_contact(session: Session, contact_id: int) -> list[Interaction]:
    return list(session.exec(
        select(Interaction).where(Interaction.contact_id == contact_id)
        .order_by(col(Interaction.at).desc())).all())


def interactions_for_application(session: Session, application_id: int) -> list[Interaction]:
    return list(session.exec(
        select(Interaction).where(Interaction.application_id == application_id)
        .order_by(col(Interaction.at).desc())).all())


def recent_interactions(session: Session, since: datetime) -> list[Interaction]:
    return list(session.exec(
        select(Interaction).where(Interaction.at >= since).order_by(col(Interaction.at).desc())).all())


def jobs_for_contact(session: Session, contact_id: int) -> list[Job]:
    job_ids = [cj.job_id for cj in session.exec(
        select(ContactJob).where(ContactJob.contact_id == contact_id)).all()]
    if not job_ids:
        return []
    return list(session.exec(select(Job).where(col(Job.id).in_(job_ids))).all())


def applications_for_contact(session: Session, contact_id: int) -> list[Application]:
    jobs = jobs_for_contact(session, contact_id)
    job_ids = [j.id for j in jobs]
    if not job_ids:
        return []
    return list(session.exec(select(Application).where(col(Application.job_id).in_(job_ids))).all())


def create_interaction(session: Session, *, contact_id: int | None = None,
                       application_id: int | None = None, kind: str, at: datetime | None = None,
                       note: str = "") -> Interaction:
    interaction = Interaction(contact_id=contact_id, application_id=application_id, kind=kind,
                              at=at or utcnow(), note=note)
    session.add(interaction)
    session.commit()
    session.refresh(interaction)
    return interaction


def delete_interaction(session: Session, interaction: Interaction) -> None:
    session.delete(interaction)
    session.commit()


def list_companies(session: Session, q: str | None = None) -> list[dict]:
    stmt = select(Application)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(col(Application.company).ilike(f"%{escaped}%", escape="\\"))
    apps = list(session.exec(stmt).all())
    grouped: dict[str, list[Application]] = {}
    for a in apps:
        grouped.setdefault(a.company_key, []).append(a)

    results = []
    for key, group in grouped.items():
        group.sort(key=lambda a: a.applied_at, reverse=True)
        contacts = session.exec(select(Contact).where(Contact.company_key == key)).all()
        results.append({
            "company": group[0].company, "company_key": key, "application_count": len(group),
            "last_applied_at": group[0].applied_at,
            "applications": [
                {"id": a.id, "title": a.title, "applied_at": a.applied_at, "stage": a.stage,
                 "tailoring_id": a.tailoring_id} for a in group],
            "contacts": [{"id": c.id, "name": c.name} for c in contacts],
        })
    results.sort(key=lambda r: r["last_applied_at"], reverse=True)
    return results


def history_timeline(session: Session, limit: int = 100) -> list[dict]:
    """Unified feed of `application_events` + `interactions`, newest first."""
    events = list(session.exec(
        select(ApplicationEvent).order_by(col(ApplicationEvent.at).desc()).limit(limit)).all())
    interactions = list(session.exec(
        select(Interaction).order_by(col(Interaction.at).desc()).limit(limit)).all())

    app_ids = {e.application_id for e in events} | {i.application_id for i in interactions
                                                     if i.application_id is not None}
    apps = {}
    if app_ids:
        apps = {a.id: a for a in session.exec(
            select(Application).where(col(Application.id).in_(app_ids))).all()}
    contact_ids = {i.contact_id for i in interactions if i.contact_id is not None}
    contacts = {}
    if contact_ids:
        contacts = {c.id: c for c in session.exec(
            select(Contact).where(col(Contact.id).in_(contact_ids))).all()}

    combined = []
    for e in events:
        app = apps.get(e.application_id)
        combined.append({
            "at": e.at, "type": "event", "kind": e.kind,
            "company": app.company if app else None, "title": app.title if app else None,
            "contact_name": None, "application_id": e.application_id, "contact_id": None,
            "note": e.note, "from_stage": e.from_stage, "to_stage": e.to_stage,
        })
    for i in interactions:
        app = apps.get(i.application_id) if i.application_id is not None else None
        contact = contacts.get(i.contact_id) if i.contact_id is not None else None
        combined.append({
            "at": i.at, "type": "interaction", "kind": i.kind,
            "company": app.company if app else (contact.company if contact else None),
            "title": app.title if app else None,
            "contact_name": contact.name if contact else None,
            "application_id": i.application_id, "contact_id": i.contact_id,
            "note": i.note, "from_stage": None, "to_stage": None,
        })
    combined.sort(key=lambda x: x["at"], reverse=True)
    return combined[:limit]
