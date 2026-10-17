from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from seekhunter.domain import JobData, dedupe_key
from seekhunter.models import (
    Job,
    JobEvaluation,
    MarketJob,
    MarketSnapshot,
    Outbox,
    Run,
    SearchProfile,
    SettingsRow,
    Tailoring,
)
from seekhunter.settings_model import AppSettings

DEFAULT_KEYWORDS = [
    "software engineer", "developer", "full stack", "frontend", "AI engineer", "graduate developer",
]


def upsert_job(session: Session, data: JobData) -> tuple[Job, bool]:
    existing = session.exec(
        select(Job).where(Job.source == data.source, Job.external_id == data.external_id)
    ).first()
    if existing:
        return existing, False
    job = Job(
        source=data.source, external_id=data.external_id, title=data.title, company=data.company,
        location=data.location, work_type=data.work_type, salary_label=data.salary_label,
        listed_at=data.listed_at, url=data.url, teaser=data.teaser, description_html=data.description_html,
        dedupe_key=dedupe_key(data.title, data.company),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job, True


def update_job_details(session: Session, job: Job, data: JobData) -> None:
    job.description_html = data.description_html or job.description_html
    if job.work_type == "unknown" and data.work_type != "unknown":
        job.work_type = data.work_type
    job.contact_phone = job.contact_phone or data.contact_phone
    job.contact_email = job.contact_email or data.contact_email
    session.add(job)
    session.commit()


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


def jobs_needing_insights(session: Session, now: datetime, limit: int) -> list[Job]:
    """SEEK jobs eligible for an insights refresh: canonical (not a duplicate), not hidden, first
    seen within the last 7 days, and not checked within the last 3 hours. Never-checked jobs
    (`insights_checked_at IS NULL`) sort first, then the longest-stale ones."""
    cutoff = now - timedelta(hours=3)
    window = now - timedelta(days=7)
    stmt = (
        select(Job)
        .where(Job.source == "seek", col(Job.canonical_job_id).is_(None), Job.status != "hidden",
               Job.first_seen_at >= window,
               or_(col(Job.insights_checked_at).is_(None), Job.insights_checked_at < cutoff))
        .order_by(col(Job.insights_checked_at).asc())
        .limit(limit)
    )
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


def _active_clause():
    return (
        col(Job.canonical_job_id).is_(None),
        Job.status != "hidden",
        or_(JobEvaluation.excluded == False, Job.force_include == True),  # noqa: E712
    )


def notification_candidates(session: Session, now: datetime) -> list[tuple[Job, JobEvaluation]]:
    stmt = (
        select(Job, JobEvaluation).join(JobEvaluation, JobEvaluation.job_id == Job.id)
        .where(*_active_clause(), col(Job.notified_at).is_(None),
               Job.first_seen_at >= now - timedelta(hours=48))
        .order_by(col(JobEvaluation.final_score).desc(), col(Job.first_seen_at).desc())
    )
    return list(session.exec(stmt).all())


def mark_notified(session: Session, job_ids: list[int], when: datetime) -> None:
    for job in session.exec(select(Job).where(col(Job.id).in_(job_ids))).all():
        job.notified_at = when
        session.add(job)
    session.commit()


def list_jobs(session: Session, view: str = "active", status: str | None = None, work_type: str | None = None,
              source: str | None = None, q: str | None = None, since: datetime | None = None,
              limit: int = 200, offset: int = 0) -> list[tuple[Job, JobEvaluation]]:
    stmt = select(Job, JobEvaluation).join(JobEvaluation, JobEvaluation.job_id == Job.id)
    if view == "excluded":
        stmt = stmt.where(JobEvaluation.excluded == True, Job.force_include == False)  # noqa: E712
        stmt = stmt.order_by(col(Job.first_seen_at).desc())
    else:
        stmt = stmt.where(col(Job.canonical_job_id).is_(None),
                          or_(JobEvaluation.excluded == False, Job.force_include == True))  # noqa: E712
        stmt = stmt.where(Job.status == status) if status else stmt.where(Job.status != "hidden")
        stmt = stmt.order_by(col(JobEvaluation.final_score).desc(), col(Job.first_seen_at).desc())
    if work_type:
        stmt = stmt.where(Job.work_type == work_type)
    if source:
        stmt = stmt.where(Job.source == source)
    if since:
        stmt = stmt.where(Job.first_seen_at >= since)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        stmt = stmt.where(or_(
            col(Job.title).ilike(like, escape="\\"), col(Job.company).ilike(like, escape="\\")))
    return list(session.exec(stmt.offset(offset).limit(limit)).all())


def count_excluded_since(session: Session, since: datetime) -> int:
    stmt = (
        select(func.count()).select_from(Job).join(JobEvaluation, JobEvaluation.job_id == Job.id)
        .where(JobEvaluation.excluded == True, Job.force_include == False,  # noqa: E712
               Job.first_seen_at >= since)
    )
    return session.exec(stmt).one()


def load_settings(session: Session) -> AppSettings:
    row = session.get(SettingsRow, 1)
    return AppSettings.model_validate(row.data) if row and row.data else AppSettings()


def save_settings(session: Session, settings: AppSettings) -> None:
    row = session.get(SettingsRow, 1) or SettingsRow(id=1)
    row.data = settings.model_dump()
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
