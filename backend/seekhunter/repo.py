from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from seekhunter.domain import JobData, dedupe_key
from seekhunter.models import Job, JobEvaluation, Outbox, Run, SearchProfile, SettingsRow
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
    session.add(job)
    session.commit()


def to_jobdata(job: Job) -> JobData:
    return JobData(source=job.source, external_id=job.external_id, title=job.title, company=job.company,
                   location=job.location, work_type=job.work_type, url=job.url, salary_label=job.salary_label,
                   listed_at=job.listed_at, teaser=job.teaser, description_html=job.description_html)


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
