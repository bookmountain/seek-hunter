import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel
from sqlmodel import Session, col, select

from seekhunter import market, repo
from seekhunter.config import get_env
from seekhunter.contacts import linkedin_search_urls
from seekhunter.db import get_session, init_db
from seekhunter.domain import APPLICATION_STAGES, INTERACTION_KINDS, company_key
from seekhunter.models import (
    Application,
    Contact,
    Interaction,
    Job,
    JobEvaluation,
    Run,
    SearchProfile,
    Tailoring,
    utcnow,
)
from seekhunter.notify import Notifier, NotifyError, format_brief
from seekhunter.profile import load_profile
from seekhunter.resume_doc import ResumeDoc
from seekhunter.security import ensure_safe_write_token, ip_allowlist_middleware, require_write
from seekhunter.settings_model import AppSettings
from seekhunter.skills import extract_skills
from seekhunter.tailor.changes import compute_changes
from seekhunter.tailor.current import current_dir, read_current
from seekhunter.tailor.models import CoverLetter
from seekhunter.tailor.pipeline import download_name, send_tailoring
from seekhunter.tailor.render import latex_hash

SPA_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
}


class ApplicationSummaryOut(BaseModel):
    id: int
    stage: str
    applied_at: datetime
    tailoring_id: int | None
    notes: str


class PriorApplicationOut(BaseModel):
    application_id: int
    title: str
    applied_at: datetime
    stage: str


class JobOut(BaseModel):
    id: int
    source: str
    title: str
    company: str
    location: str
    city: str
    work_type: str
    salary_label: str | None
    listed_at: datetime | None
    first_seen_at: datetime
    url: str
    status: str
    notes: str
    force_include: bool
    excluded: bool
    reasons: list[str]
    snippets: dict[str, str]
    rule_score: int
    llm_score: int | None
    llm_note: str | None
    final_score: int
    matched_skills: list[str]
    flags: list[str]
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    contact_linkedin: str | None
    contact_search: dict[str, str]
    applicant_count: int | None
    applicant_volume: str | None
    resume_pct: int | None
    cover_letter_pct: int | None
    insights_checked_at: datetime | None
    application: ApplicationSummaryOut | None
    prior_applications: list[PriorApplicationOut]


class JobDetailOut(JobOut):
    description_html: str
    teaser: str


class CityCountOut(BaseModel):
    city: str
    count: int


class NotificationItemOut(BaseModel):
    type: str  # job | tailoring | follow_up
    at: datetime
    title: str
    subtitle: str
    city: str | None = None
    score: int | None = None
    job_id: int | None = None
    tailoring_id: int | None = None
    application_id: int | None = None
    unread: bool


class NotificationsOut(BaseModel):
    read_at: datetime
    unread_count: int
    by_city: list[CityCountOut]
    items: list[NotificationItemOut]


class JobPatch(BaseModel):
    status: str | None = None
    notes: str | None = None


class UnexcludeIn(BaseModel):
    allowlist_employer: bool = False


class ApplicationOut(BaseModel):
    id: int
    job_id: int | None
    company: str
    company_key: str
    title: str
    url: str | None
    location: str | None
    applied_at: datetime
    tailoring_id: int | None
    stage: str
    source: str
    notes: str
    created_at: datetime
    updated_at: datetime


class ContactInlineIn(BaseModel):
    name: str
    role: str | None = None
    phone: str | None = None
    email: str | None = None
    linkedin: str | None = None


class ApplicationCreateIn(BaseModel):
    company: str
    title: str
    url: str | None = None
    location: str | None = None
    applied_at: datetime | None = None
    notes: str = ""
    contact: ContactInlineIn | None = None


class ApplicationPatchIn(BaseModel):
    stage: str | None = None
    notes: str | None = None
    applied_at: datetime | None = None
    tailoring_id: int | None = None


class ContactOut(BaseModel):
    id: int
    name: str
    company: str
    company_key: str
    role: str | None
    phone: str | None
    email: str | None
    linkedin: str | None
    notes: str
    created_at: datetime
    updated_at: datetime
    last_interaction: datetime | None
    interaction_count: int
    job_count: int
    application_count: int


class ContactCreateIn(BaseModel):
    name: str
    company: str = ""
    role: str | None = None
    phone: str | None = None
    email: str | None = None
    linkedin: str | None = None
    notes: str = ""


class ContactPatchIn(BaseModel):
    name: str | None = None
    company: str | None = None
    role: str | None = None
    phone: str | None = None
    email: str | None = None
    linkedin: str | None = None
    notes: str | None = None


class InteractionOut(BaseModel):
    id: int
    contact_id: int | None
    application_id: int | None
    kind: str
    at: datetime
    note: str
    created_at: datetime


class InteractionCreateIn(BaseModel):
    contact_id: int | None = None
    application_id: int | None = None
    kind: str
    at: datetime | None = None
    note: str = ""


class ContactLogIn(BaseModel):
    kind: str
    note: str = ""


class ContactJobOut(BaseModel):
    id: int
    title: str
    company: str
    url: str


class ContactDetailOut(ContactOut):
    interactions: list[InteractionOut]
    jobs: list[ContactJobOut]
    applications: list[ApplicationOut]


class CompanyApplicationOut(BaseModel):
    id: int
    title: str
    applied_at: datetime
    stage: str
    tailoring_id: int | None


class CompanyContactOut(BaseModel):
    id: int
    name: str


class CompanyOut(BaseModel):
    company: str
    company_key: str
    application_count: int
    last_applied_at: datetime
    applications: list[CompanyApplicationOut]
    contacts: list[CompanyContactOut]


class HistoryEventOut(BaseModel):
    at: datetime
    type: str
    kind: str
    company: str | None
    title: str | None
    contact_name: str | None
    application_id: int | None
    contact_id: int | None
    note: str
    from_stage: str | None
    to_stage: str | None


class SearchProfileIn(BaseModel):
    name: str
    keywords: str
    location: str
    work_types: list[str] = []
    sources: list[str] = ["seek", "jora"]
    enabled: bool = True


class TailorStartOut(BaseModel):
    tailoring_id: int
    status: str
    reused: bool


class TailoringOut(BaseModel):
    id: int
    job_id: int
    status: str
    progress: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    provider: str | None
    error: str | None
    send_requested: bool
    sent_at: datetime | None
    resume_hash: str | None
    pages: dict[str, int]
    warnings_count: int


class TailoringListItem(TailoringOut):
    job_title: str
    company: str
    city: str | None
    resume_pdf: str | None
    cover_letter_pdf: str | None
    thumbnail: str | None
    applied_application_id: int | None


class CoverLetterOut(BaseModel):
    greeting: str
    paragraphs: list[str]
    sign_off: str
    text: str
    word_count: int


class TailoringFilesOut(BaseModel):
    resume_pdf: str
    cover_letter_pdf: str
    resume_pages: list[str]
    cover_letter_pages: list[str]


class ResumeCurrentOut(BaseModel):
    hash: str | None
    ready: bool
    pages: int
    pdf_url: str | None
    page_urls: list[str]
    error: str | None


class TailoringJobOut(BaseModel):
    id: int
    title: str
    company: str
    location: str
    work_type: str
    contact_name: str | None


class TailoringDetailOut(TailoringOut):
    job: TailoringJobOut
    warnings: list[str]
    keywords_matched: list[str]
    gaps: list[str]
    cover_letter: CoverLetterOut | None
    changes: list[dict]
    files: TailoringFilesOut | None
    current: ResumeCurrentOut | None


class SendOut(BaseModel):
    sent: bool
    sent_at: datetime | None


class CityOverviewOut(BaseModel):
    city: str
    total: int
    flexible: int
    flexible_share: float
    work_type_mix: dict[str, int]
    role_family_mix: dict[str, int]
    salary_p25: float | None
    salary_p50: float | None
    salary_p75: float | None
    salary_sample_size: int
    detailed_sample_size: int


class SkillShareOut(BaseModel):
    skill: str
    count: int
    share: float
    you_have: bool


class CityShareOut(BaseModel):
    city: str
    shares: dict[str, float]
    detailed_sample_size: int


class CompareOut(BaseModel):
    skills: list[str]
    cities: list[CityShareOut]


class GapOut(BaseModel):
    skill: str
    count: int
    share: float
    example_titles: list[str]
    role_families: list[str]


class TrendPointOut(BaseModel):
    date: datetime
    shares: dict[str, float]


class TrendsOut(BaseModel):
    city: str
    skills: list[str]
    points: list[TrendPointOut]


class RoleFamilyOut(BaseModel):
    role_family: str
    count: int
    flexible_share: float
    top_skills: list[str]


def _application_summary(app: Application | None) -> ApplicationSummaryOut | None:
    if not app:
        return None
    return ApplicationSummaryOut(id=app.id, stage=app.stage, applied_at=app.applied_at,
                                 tailoring_id=app.tailoring_id, notes=app.notes)


def _prior_applications(apps: list[Application], exclude_job_id: int | None) -> list[PriorApplicationOut]:
    """`apps` is already newest-applied-first (see repo.applications_by_company_keys); this just
    drops the job's own application and caps at 5."""
    out = []
    for a in apps:
        if exclude_job_id is not None and a.job_id == exclude_job_id:
            continue
        out.append(PriorApplicationOut(application_id=a.id, title=a.title, applied_at=a.applied_at,
                                       stage=a.stage))
        if len(out) >= 5:
            break
    return out


def _enrich_one(session: Session, job: Job) -> tuple[Application | None, list[PriorApplicationOut]]:
    """Single-job version of the jobs-list batch enrichment below, for the detail/patch/unexclude
    endpoints where only one job needs application/prior_applications data."""
    application = repo.get_application_by_job(session, job.id)
    key = company_key(job.company)
    apps = repo.applications_by_company_keys(session, {key}).get(key, [])
    return application, _prior_applications(apps, job.id)


def _application_out(a: Application) -> ApplicationOut:
    return ApplicationOut(id=a.id, job_id=a.job_id, company=a.company, company_key=a.company_key,
                          title=a.title, url=a.url, location=a.location, applied_at=a.applied_at,
                          tailoring_id=a.tailoring_id, stage=a.stage, source=a.source, notes=a.notes,
                          created_at=a.created_at, updated_at=a.updated_at)


def _contact_out(session: Session, c: Contact) -> ContactOut:
    stats = repo.contact_stats(session, c.id)
    return ContactOut(id=c.id, name=c.name, company=c.company, company_key=c.company_key, role=c.role,
                      phone=c.phone, email=c.email, linkedin=c.linkedin, notes=c.notes,
                      created_at=c.created_at, updated_at=c.updated_at, **stats)


def _interaction_out(i: Interaction) -> InteractionOut:
    return InteractionOut(id=i.id, contact_id=i.contact_id, application_id=i.application_id, kind=i.kind,
                          at=i.at, note=i.note, created_at=i.created_at)


def _job_out(job: Job, ev: JobEvaluation, application: Application | None = None,
            priors: list[PriorApplicationOut] | None = None, detail: bool = False) -> JobOut:
    base = dict(
        id=job.id, source=job.source, title=job.title, company=job.company, location=job.location,
        city=job.city or "other",
        work_type=job.work_type, salary_label=job.salary_label, listed_at=job.listed_at,
        first_seen_at=job.first_seen_at, url=job.url, status=job.status, notes=job.notes,
        force_include=job.force_include, excluded=ev.excluded, reasons=ev.reasons, snippets=ev.snippets,
        rule_score=ev.rule_score, llm_score=ev.llm_score, llm_note=ev.llm_note, final_score=ev.final_score,
        matched_skills=ev.matched_skills, flags=ev.flags, contact_name=job.contact_name,
        contact_phone=job.contact_phone, contact_email=job.contact_email,
        contact_linkedin=job.contact_linkedin,
        contact_search=linkedin_search_urls(job.contact_name, job.company),
        applicant_count=job.applicant_count, applicant_volume=job.applicant_volume,
        resume_pct=job.resume_pct, cover_letter_pct=job.cover_letter_pct,
        insights_checked_at=job.insights_checked_at, application=_application_summary(application),
        prior_applications=priors or [],
    )
    if detail:
        return JobDetailOut(**base, description_html=job.description_html, teaser=job.teaser)
    return JobOut(**base)


def _competition_line(job: Job) -> str | None:
    if job.applicant_count is None:
        return None
    bits = [f"{job.applicant_count} applicants"]
    if job.applicant_volume:
        bits[0] += f" ({job.applicant_volume})"
    if job.resume_pct is not None:
        bits.append(f"{job.resume_pct}% resume")
    if job.cover_letter_pct is not None:
        bits.append(f"{job.cover_letter_pct}% cover letter")
    line = " · ".join(bits)
    if job.insights_checked_at:
        line += f" · checked {job.insights_checked_at.isoformat()}"
    return line


def _get_job(session: Session, job_id: int) -> tuple[Job, JobEvaluation]:
    job = session.get(Job, job_id)
    ev = session.exec(select(JobEvaluation).where(JobEvaluation.job_id == job_id)).first()
    if not job or not ev:
        raise HTTPException(404, "job not found")
    return job, ev


TAILOR_KINDS = ("resume", "cover_letter")
PREVIEW_RESPAWN_SECONDS = 60
IMMUTABLE = {"Cache-Control": "private, max-age=86400"}
NO_CACHE = {"Cache-Control": "no-cache"}


def _spawn_cli(*args: str) -> None:
    subprocess.Popen([sys.executable, "-m", "seekhunter.cli", *args], start_new_session=True)


def _tailoring_out(t: Tailoring) -> TailoringOut:
    pages = {k: int(v) for k, v in (t.result or {}).get("pages", {}).items()}
    return TailoringOut(
        id=t.id, job_id=t.job_id, status=t.status, progress=t.progress, created_at=t.created_at,
        started_at=t.started_at, finished_at=t.finished_at, provider=t.provider, error=t.error,
        send_requested=t.send_requested, sent_at=t.sent_at, resume_hash=t.resume_hash, pages=pages,
        warnings_count=len(t.warnings or []))


def _current_out(data_dir: Path, resume_hash: str | None, error: str | None = None) -> ResumeCurrentOut:
    meta = read_current(data_dir, resume_hash) if resume_hash else None
    if not meta:
        return ResumeCurrentOut(hash=resume_hash, ready=False, pages=0, pdf_url=None, page_urls=[],
                                error=error)
    h, n = meta["hash"], int(meta["pages"])
    return ResumeCurrentOut(
        hash=h, ready=True, pages=n, pdf_url=f"/api/resume/current.pdf?hash={h}",
        page_urls=[f"/api/resume/current/pages/{i}.png?hash={h}" for i in range(1, n + 1)], error=None)


def _tailoring_detail(t: Tailoring, job: Job, data_dir: Path) -> TailoringDetailOut:
    result = t.result or {}
    done = t.status == "done" and bool(result)
    letter = changes = files = current_info = None
    if done:
        cl = CoverLetter.model_validate(result.get("cover_letter") or {})
        letter = CoverLetterOut(greeting=cl.greeting, paragraphs=cl.paragraphs, sign_off=cl.sign_off,
                                text=cl.text(), word_count=cl.word_count())
        changes = compute_changes(ResumeDoc.model_validate(result["base"]),
                                  ResumeDoc.model_validate(result["tailored"]))
        pages = result.get("pages", {})
        base = f"/api/tailorings/{t.id}"
        files = TailoringFilesOut(
            resume_pdf=f"{base}/resume.pdf", cover_letter_pdf=f"{base}/cover_letter.pdf",
            resume_pages=[f"{base}/pages/resume/{i}.png" for i in range(1, pages.get("resume", 0) + 1)],
            cover_letter_pages=[f"{base}/pages/cover_letter/{i}.png"
                                for i in range(1, pages.get("cover_letter", 0) + 1)])
        current_info = _current_out(data_dir, t.resume_hash)
    return TailoringDetailOut(
        **_tailoring_out(t).model_dump(),
        job=TailoringJobOut(id=job.id, title=job.title, company=job.company, location=job.location,
                            work_type=job.work_type, contact_name=job.contact_name),
        warnings=list(t.warnings or []), keywords_matched=list(result.get("keywords_matched", [])),
        gaps=list(result.get("gaps", [])), cover_letter=letter, changes=changes or [], files=files,
        current=current_info)


def _get_tailoring(session: Session, tid: int) -> tuple[Tailoring, Job]:
    t = session.get(Tailoring, tid)
    job = session.get(Job, t.job_id) if t else None
    if not t or not job:
        raise HTTPException(404, "tailoring not found")
    return t, job


def _tailoring_file(t: Tailoring, name: str) -> Path:
    if t.status != "done" or not t.out_dir:
        raise HTTPException(404, "tailoring not finished")
    path = Path(t.out_dir) / name
    if not path.is_file():
        raise HTTPException(404, "file not found")
    return path


def _notifications_payload(session: Session, now: datetime, limit: int) -> NotificationsOut:
    """Shared by GET /api/notifications and POST /api/notifications/read. `jobs` and `tailoring`
    items are combined and sorted newest-first then capped at `limit`; `follow_up` items are always
    included in full (they're a small, current snapshot, not a time-windowed backlog) and don't
    count toward `unread_count`."""
    _stored, since = repo.notifications_read_at(session, now)
    job_rows = repo.unread_job_items(session, since)
    tailoring_rows = repo.unread_tailoring_items(session, since)
    due = repo.follow_ups_due(session, now)

    job_items = [
        NotificationItemOut(type="job", at=j.first_seen_at, title=j.title, subtitle=j.company,
                            city=j.city or "other", score=ev.final_score, job_id=j.id, unread=True)
        for j, ev in job_rows
    ]

    tailoring_items: list[NotificationItemOut] = []
    if tailoring_rows:
        job_ids = {t.job_id for t in tailoring_rows}
        jobs_by_id = {j.id: j for j in session.exec(select(Job).where(col(Job.id).in_(job_ids))).all()}
        for t in tailoring_rows:
            job = jobs_by_id.get(t.job_id)
            tailoring_items.append(NotificationItemOut(
                type="tailoring", at=t.finished_at, title=job.title if job else f"Job #{t.job_id}",
                subtitle=f"Tailoring {t.status}", job_id=t.job_id, tailoring_id=t.id, unread=True))

    combined = sorted(job_items + tailoring_items, key=lambda i: i.at, reverse=True)[:limit]

    follow_up_items = [
        NotificationItemOut(type="follow_up", at=a.applied_at, title=a.title, subtitle=a.company,
                            application_id=a.id, unread=False)
        for a in due
    ]

    by_city_counts: dict[str, int] = {}
    for item in job_items:
        by_city_counts[item.city] = by_city_counts.get(item.city, 0) + 1
    by_city = [CityCountOut(city=c, count=n) for c, n in sorted(by_city_counts.items())]

    return NotificationsOut(
        read_at=since, unread_count=len(job_items) + len(tailoring_items), by_city=by_city,
        items=combined + follow_up_items)


def create_app(init: bool = True) -> FastAPI:
    env = get_env()
    ensure_safe_write_token(env)
    if init:
        init_db()
        from seekhunter.db import get_engine

        with Session(get_engine()) as s:
            repo.ensure_seed(s)

    docs_kwargs = {} if env.seekhunter_dev else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="SeekHunter", **docs_kwargs)
    app.middleware("http")(ip_allowlist_middleware)
    write = [Depends(require_write)]

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/meta")
    def meta() -> dict:
        """Lets the UI know whether it needs to ask for the write token at all."""
        return {"write_requires_token": get_env().write_requires_token}

    @app.get("/api/jobs", response_model=list[JobOut])
    def list_jobs(view: str = "active", status: str | None = None, work_type: str | None = None,
                  source: str | None = None, q: str | None = None, city: str | None = None,
                  limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
                  session: Session = Depends(get_session)):
        rows = repo.list_jobs(session, view=view, status=status, work_type=work_type, source=source, q=q,
                              city=city, limit=limit, offset=offset)
        # Batched (not per-job) so this stays O(1) queries regardless of list size (~300 jobs).
        job_ids = [j.id for j, _ in rows]
        apps_by_job = repo.applications_by_job_ids(session, job_ids)
        keys = {company_key(j.company) for j, _ in rows}
        apps_by_key = repo.applications_by_company_keys(session, keys)
        return [
            _job_out(j, e, application=apps_by_job.get(j.id),
                    priors=_prior_applications(apps_by_key.get(company_key(j.company), []), j.id))
            for j, e in rows
        ]

    @app.get("/api/jobs/cities", response_model=list[CityCountOut])
    def jobs_cities(view: str = "active", session: Session = Depends(get_session)):
        return [CityCountOut(city=c or "other", count=n) for c, n in repo.job_city_counts(session, view=view)]

    @app.get("/api/jobs/{job_id}", response_model=JobDetailOut)
    def get_job(job_id: int, session: Session = Depends(get_session)):
        job, ev = _get_job(session, job_id)
        application, priors = _enrich_one(session, job)
        return _job_out(job, ev, application=application, priors=priors, detail=True)

    @app.patch("/api/jobs/{job_id}", response_model=JobOut, dependencies=write)
    def patch_job(job_id: int, body: JobPatch, session: Session = Depends(get_session)):
        job, ev = _get_job(session, job_id)
        if body.status is not None:
            if body.status not in {"new", "saved", "applied", "hidden"}:
                raise HTTPException(422, "invalid status")
            job.status = body.status
        if body.notes is not None:
            job.notes = body.notes
        session.add(job)
        session.commit()
        if body.status == "applied":
            repo.ensure_application_for_job(session, job, utcnow())
            if job.contact_name:
                contact = repo.upsert_contact(session, name=job.contact_name, company=job.company,
                                              role="Recruiter", phone=job.contact_phone,
                                              email=job.contact_email, linkedin=job.contact_linkedin)
                repo.link_contact_job(session, contact.id, job.id)
        application, priors = _enrich_one(session, job)
        return _job_out(job, ev, application=application, priors=priors)

    @app.post("/api/jobs/{job_id}/unexclude", response_model=JobOut, dependencies=write)
    def unexclude(job_id: int, body: UnexcludeIn, session: Session = Depends(get_session)):
        job, ev = _get_job(session, job_id)
        job.force_include = True
        session.add(job)
        session.commit()
        if body.allowlist_employer and job.company:
            settings = repo.load_settings(session)
            existing = {e.casefold() for e in settings.employer_allowlist}
            if job.company.casefold() not in existing:
                settings.employer_allowlist.append(job.company)
                repo.save_settings(session, settings)
        application, priors = _enrich_one(session, job)
        return _job_out(job, ev, application=application, priors=priors)

    # ------------------------------------------------------------------ application history
    def _get_application(session: Session, aid: int) -> Application:
        app_row = session.get(Application, aid)
        if not app_row:
            raise HTTPException(404, "application not found")
        return app_row

    def _get_contact(session: Session, cid: int) -> Contact:
        contact = session.get(Contact, cid)
        if not contact:
            raise HTTPException(404, "contact not found")
        return contact

    @app.get("/api/applications", response_model=list[ApplicationOut])
    def list_applications(stage: str | None = None, q: str | None = None,
                          session: Session = Depends(get_session)):
        return [_application_out(a) for a in repo.list_applications(session, stage=stage, q=q)]

    @app.post("/api/applications", response_model=ApplicationOut, status_code=201, dependencies=write)
    def create_application(body: ApplicationCreateIn, session: Session = Depends(get_session)):
        app_row = repo.create_application(session, job_id=None, company=body.company, title=body.title,
                                          url=body.url, location=body.location,
                                          applied_at=body.applied_at, source="manual", notes=body.notes)
        if body.contact:
            # Not linked via contact_jobs: a manual application (outside SeekHunter) has no job row.
            repo.upsert_contact(session, name=body.contact.name, company=body.company,
                               role=body.contact.role, phone=body.contact.phone,
                               email=body.contact.email, linkedin=body.contact.linkedin)
        return _application_out(app_row)

    @app.patch("/api/applications/{aid}", response_model=ApplicationOut, dependencies=write)
    def patch_application(aid: int, body: ApplicationPatchIn, session: Session = Depends(get_session)):
        app_row = _get_application(session, aid)
        if body.stage is not None and body.stage not in APPLICATION_STAGES:
            raise HTTPException(422, "invalid stage")
        updated = repo.update_application(session, app_row, stage=body.stage, notes=body.notes,
                                          applied_at=body.applied_at, tailoring_id=body.tailoring_id)
        return _application_out(updated)

    @app.delete("/api/applications/{aid}", status_code=204, dependencies=write)
    def delete_application(aid: int, session: Session = Depends(get_session)):
        app_row = session.get(Application, aid)
        if app_row:
            repo.delete_application(session, app_row)
        return Response(status_code=204)

    @app.get("/api/contacts", response_model=list[ContactOut])
    def list_contacts(q: str | None = None, session: Session = Depends(get_session)):
        return [_contact_out(session, c) for c in repo.list_contacts(session, q=q)]

    @app.post("/api/contacts", response_model=ContactOut, status_code=201, dependencies=write)
    def create_contact(body: ContactCreateIn, session: Session = Depends(get_session)):
        contact = repo.upsert_contact(session, name=body.name, company=body.company, role=body.role,
                                      phone=body.phone, email=body.email, linkedin=body.linkedin,
                                      notes=body.notes)
        return _contact_out(session, contact)

    @app.patch("/api/contacts/{cid}", response_model=ContactOut, dependencies=write)
    def patch_contact(cid: int, body: ContactPatchIn, session: Session = Depends(get_session)):
        contact = _get_contact(session, cid)
        for field in ("name", "company", "role", "phone", "email", "linkedin", "notes"):
            value = getattr(body, field)
            if value is not None:
                setattr(contact, field, value)
        if body.company is not None:
            contact.company_key = company_key(body.company)
        contact.updated_at = utcnow()
        session.add(contact)
        session.commit()
        session.refresh(contact)
        return _contact_out(session, contact)

    @app.get("/api/contacts/{cid}", response_model=ContactDetailOut)
    def get_contact(cid: int, session: Session = Depends(get_session)):
        contact = _get_contact(session, cid)
        base = _contact_out(session, contact)
        interactions = [_interaction_out(i) for i in repo.interactions_for_contact(session, cid)]
        jobs = [ContactJobOut(id=j.id, title=j.title, company=j.company, url=j.url)
               for j in repo.jobs_for_contact(session, cid)]
        applications = [_application_out(a) for a in repo.applications_for_contact(session, cid)]
        return ContactDetailOut(**base.model_dump(), interactions=interactions, jobs=jobs,
                                applications=applications)

    @app.post("/api/interactions", response_model=InteractionOut, status_code=201, dependencies=write)
    def create_interaction(body: InteractionCreateIn, session: Session = Depends(get_session)):
        if not body.contact_id and not body.application_id:
            raise HTTPException(422, "contact_id or application_id required")
        if body.kind not in INTERACTION_KINDS:
            raise HTTPException(422, "invalid kind")
        if body.contact_id and not session.get(Contact, body.contact_id):
            raise HTTPException(404, "contact not found")
        if body.application_id and not session.get(Application, body.application_id):
            raise HTTPException(404, "application not found")
        interaction = repo.create_interaction(session, contact_id=body.contact_id,
                                              application_id=body.application_id, kind=body.kind,
                                              at=body.at, note=body.note)
        return _interaction_out(interaction)

    @app.delete("/api/interactions/{iid}", status_code=204, dependencies=write)
    def delete_interaction(iid: int, session: Session = Depends(get_session)):
        interaction = session.get(Interaction, iid)
        if interaction:
            repo.delete_interaction(session, interaction)
        return Response(status_code=204)

    @app.post("/api/jobs/{job_id}/contact-log", response_model=InteractionOut, status_code=201,
              dependencies=write)
    def job_contact_log(job_id: int, body: ContactLogIn, session: Session = Depends(get_session)):
        job, _ev = _get_job(session, job_id)
        if not job.contact_name:
            raise HTTPException(422, "job has no recruiter contact")
        if body.kind not in INTERACTION_KINDS:
            raise HTTPException(422, "invalid kind")
        contact = repo.upsert_contact(session, name=job.contact_name, company=job.company, role="Recruiter",
                                      phone=job.contact_phone, email=job.contact_email,
                                      linkedin=job.contact_linkedin)
        repo.link_contact_job(session, contact.id, job.id)
        interaction = repo.create_interaction(session, contact_id=contact.id, kind=body.kind,
                                              note=body.note)
        return _interaction_out(interaction)

    @app.get("/api/companies", response_model=list[CompanyOut])
    def list_companies(q: str | None = None, session: Session = Depends(get_session)):
        return repo.list_companies(session, q=q)

    @app.get("/api/history", response_model=list[HistoryEventOut])
    def history(limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)):
        return repo.history_timeline(session, limit=limit)

    @app.get("/api/history/summary", response_class=PlainTextResponse)
    def history_summary(days: int = Query(14, ge=1, le=90), session: Session = Depends(get_session)):
        now = utcnow()
        since = now - timedelta(days=days)
        counts = repo.stage_counts(session)
        lines = ["Applications by stage:"]
        stage_bits = [f"{stage} {counts[stage]}" for stage in APPLICATION_STAGES if counts.get(stage)]
        lines.append(", ".join(stage_bits) if stage_bits else "none yet")

        recent_apps = repo.recent_applications(session, since)
        lines.append("")
        lines.append(f"Recent applications (last {days}d): {len(recent_apps)}")
        for a in recent_apps[:10]:
            age = (now - a.applied_at).days
            lines.append(f"- {a.company} · {a.title} · {age}d ago · {a.stage}")

        recent_ints = repo.recent_interactions(session, since)
        lines.append("")
        lines.append(f"Recent interactions (last {days}d): {len(recent_ints)}")
        for i in recent_ints[:10]:
            contact = session.get(Contact, i.contact_id) if i.contact_id else None
            application = session.get(Application, i.application_id) if i.application_id else None
            who = contact.name if contact else (application.company if application else "unknown")
            age = (now - i.at).days
            note = f" — {i.note}" if i.note else ""
            lines.append(f"- {who}: {i.kind} · {age}d ago{note}")

        due = repo.follow_ups_due(session, now)
        lines.append("")
        lines.append(f"Follow-ups due (applied, no activity in 7d): {len(due)}")
        for a in due[:10]:
            age = (now - a.applied_at).days
            lines.append(f"- {a.company} · {a.title} · {age}d")

        return "\n".join(lines)

    @app.get("/api/search-profiles", response_model=list[SearchProfile])
    def list_profiles(session: Session = Depends(get_session)):
        return repo.list_search_profiles(session)

    @app.post("/api/search-profiles", response_model=SearchProfile, dependencies=write)
    def create_profile(body: SearchProfileIn, session: Session = Depends(get_session)):
        profile = SearchProfile(**body.model_dump())
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile

    @app.put("/api/search-profiles/{pid}", response_model=SearchProfile, dependencies=write)
    def update_profile(pid: int, body: SearchProfileIn, session: Session = Depends(get_session)):
        profile = session.get(SearchProfile, pid)
        if not profile:
            raise HTTPException(404, "not found")
        for k, v in body.model_dump().items():
            setattr(profile, k, v)
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile

    @app.delete("/api/search-profiles/{pid}", status_code=204, dependencies=write)
    def delete_profile(pid: int, session: Session = Depends(get_session)):
        profile = session.get(SearchProfile, pid)
        if profile:
            session.delete(profile)
            session.commit()
        return Response(status_code=204)

    @app.get("/api/settings", response_model=AppSettings)
    def get_settings(session: Session = Depends(get_session)):
        return repo.load_settings(session)

    @app.put("/api/settings", response_model=AppSettings, dependencies=write)
    def put_settings(body: AppSettings, session: Session = Depends(get_session)):
        # The notification-bell "last read" marker is server-owned; never let a UI PUT (which
        # round-trips whatever GET /api/settings returned earlier) clobber it with a stale value.
        body.notifications_read_at = repo.load_settings(session).notifications_read_at
        repo.save_settings(session, body)
        return body

    @app.get("/api/notifications", response_model=NotificationsOut)
    def get_notifications(limit: int = Query(20, ge=1, le=200), session: Session = Depends(get_session)):
        return _notifications_payload(session, utcnow(), limit)

    @app.post("/api/notifications/read", response_model=NotificationsOut, dependencies=write)
    def mark_notifications_read(limit: int = Query(20, ge=1, le=200),
                                session: Session = Depends(get_session)):
        now = utcnow()
        repo.mark_notifications_read(session, now)
        return _notifications_payload(session, now, limit)

    @app.get("/api/runs", response_model=list[Run])
    def list_runs(session: Session = Depends(get_session)):
        return repo.recent_runs(session, "crawl", 50)

    @app.post("/api/runs", status_code=202, dependencies=write)
    def trigger_run() -> dict:
        subprocess.Popen([sys.executable, "-m", "seekhunter.cli", "run"], start_new_session=True)
        return {"started": True}

    @app.post("/api/notify/test", dependencies=write)
    def notify_test() -> dict:
        try:
            Notifier(env.openclaw_bin, env.telegram_target).send("SeekHunter test message")
        except NotifyError as e:
            raise HTTPException(502, str(e)) from e
        return {"sent": True}

    @app.get("/api/jobs/{job_id}/brief", response_class=PlainTextResponse)
    def job_brief(job_id: int, session: Session = Depends(get_session)):
        job, ev = _get_job(session, job_id)
        data = repo.to_jobdata(job)
        try:
            profile_skills = load_profile(env.resume_dir).skills
        except FileNotFoundError:
            profile_skills = set()
        missing = sorted(extract_skills(f"{job.title} {data.text}") - profile_skills)
        return format_brief(
            job_id=job.id, title=job.title, company=job.company, location=job.location,
            work_type=job.work_type, salary=job.salary_label, score=ev.final_score,
            rule_score=ev.rule_score, llm_score=ev.llm_score, llm_note=ev.llm_note,
            matched=ev.matched_skills, missing=missing, flags=ev.flags, reasons=ev.reasons,
            status=job.status, url=job.url, description=data.text,
            contact_name=job.contact_name, contact_phone=job.contact_phone,
            contact_email=job.contact_email, contact_linkedin=job.contact_linkedin,
            contact_search=linkedin_search_urls(job.contact_name, job.company),
            competition=_competition_line(job),
        )

    @app.get("/api/summary", response_class=PlainTextResponse)
    def summary(hours: int = Query(24, ge=1, le=720), session: Session = Depends(get_session)):
        rows = repo.list_jobs(session, view="active", since=utcnow() - timedelta(hours=hours), limit=30)
        if not rows:
            return f"No new jobs in the last {hours}h."
        return "\n".join(
            f"#{j.id} [{e.final_score}] {j.title} — {j.company} · {j.location} · {j.work_type} · {j.status}"
            for j, e in rows
        )

    # ------------------------------------------------------------------ market insights
    def _valid_city(city: str) -> str:
        if city not in market.CITY_ORDER:
            raise HTTPException(422, f"city must be one of {market.CITY_ORDER}")
        return city

    def _profile_skills() -> set[str]:
        try:
            return load_profile(env.resume_dir).skills
        except FileNotFoundError:
            return set()

    def _skill_list(skills: str) -> list[str]:
        return [s.strip() for s in skills.split(",") if s.strip()]

    @app.get("/api/insights/overview", response_model=list[CityOverviewOut])
    def insights_overview(days: int = Query(14, ge=1, le=90), session: Session = Depends(get_session)):
        return market.overview(session, days=days)

    @app.get("/api/insights/skills", response_model=list[SkillShareOut])
    def insights_skills(city: str, days: int = Query(14, ge=1, le=90), role_family: str | None = None,
                        session: Session = Depends(get_session)):
        _valid_city(city)
        return market.skill_demand(session, city, days=days, role_family=role_family,
                                   profile_skills=_profile_skills(), top=40)

    @app.get("/api/insights/compare", response_model=CompareOut)
    def insights_compare(skills: str, days: int = Query(14, ge=1, le=90),
                         session: Session = Depends(get_session)):
        skill_list = _skill_list(skills)
        rows = market.compare(session, skill_list, days=days)
        return CompareOut(skills=skill_list, cities=[CityShareOut(**r) for r in rows])

    @app.get("/api/insights/gaps", response_model=list[GapOut])
    def insights_gaps(city: str, days: int = Query(14, ge=1, le=90), session: Session = Depends(get_session)):
        _valid_city(city)
        return market.gaps(session, city, days=days, profile_skills=_profile_skills(), top=30)

    @app.get("/api/insights/trends", response_model=TrendsOut)
    def insights_trends(city: str, skills: str, weeks: int = Query(8, ge=1, le=52),
                        session: Session = Depends(get_session)):
        _valid_city(city)
        skill_list = _skill_list(skills)
        points = market.trends(session, city, skill_list, weeks=weeks)
        return TrendsOut(city=city, skills=skill_list, points=points)

    @app.get("/api/insights/roles", response_model=list[RoleFamilyOut])
    def insights_roles(city: str, days: int = Query(14, ge=1, le=90),
                       session: Session = Depends(get_session)):
        _valid_city(city)
        return market.roles(session, city, days=days)

    # ------------------------------------------------------------------ tailoring
    preview_spawned: dict[str, float] = {}

    @app.post("/api/jobs/{job_id}/tailor", response_model=TailorStartOut, status_code=202,
              dependencies=write)
    def start_tailoring(job_id: int, send: bool = False, session: Session = Depends(get_session)):
        if not session.get(Job, job_id):
            raise HTTPException(404, "job not found")
        active = repo.active_tailoring(session, job_id, utcnow())
        if active:
            if send and not active.send_requested:
                active.send_requested = True
                repo.save_tailoring(session, active)
            return TailorStartOut(tailoring_id=active.id, status=active.status, reused=True)
        t = repo.create_tailoring(session, job_id, send=send)
        _spawn_cli("tailor", str(job_id), "--tailoring-id", str(t.id), *(["--send"] if send else []))
        return TailorStartOut(tailoring_id=t.id, status=t.status, reused=False)

    @app.get("/api/jobs/{job_id}/tailorings", response_model=list[TailoringOut])
    def list_tailorings(job_id: int, session: Session = Depends(get_session)):
        if not session.get(Job, job_id):
            raise HTTPException(404, "job not found")
        return [_tailoring_out(t) for t in repo.list_tailorings(session, job_id)]

    @app.get("/api/tailorings", response_model=list[TailoringListItem])
    def all_tailorings(limit: int = Query(100, ge=1, le=500), q: str | None = None,
                       session: Session = Depends(get_session)):
        """Every tailored resume, newest first, for the Resumes page."""
        rows = repo.list_all_tailorings(session, limit=limit)
        job_ids = {t.job_id for t in rows}
        jobs = {j.id: j for j in session.exec(select(Job).where(col(Job.id).in_(job_ids))).all()}
        applied = {a.tailoring_id: a.id for a in session.exec(
            select(Application).where(col(Application.tailoring_id).in_([t.id for t in rows]))).all()}
        out = []
        for t in rows:
            job = jobs.get(t.job_id)
            title, company = (job.title, job.company) if job else ("(deleted job)", "")
            if q and q.lower() not in f"{title} {company}".lower():
                continue
            done = t.status == "done"
            out.append(TailoringListItem(
                **_tailoring_out(t).model_dump(), job_title=title, company=company,
                city=getattr(job, "city", None) if job else None,
                resume_pdf=f"/api/tailorings/{t.id}/resume.pdf" if done else None,
                cover_letter_pdf=f"/api/tailorings/{t.id}/cover_letter.pdf" if done else None,
                thumbnail=f"/api/tailorings/{t.id}/pages/resume/1.png" if done else None,
                applied_application_id=applied.get(t.id)))
        return out

    @app.get("/api/tailorings/{tid}", response_model=TailoringDetailOut)
    def get_tailoring(tid: int, session: Session = Depends(get_session)):
        t, job = _get_tailoring(session, tid)
        return _tailoring_detail(t, job, env.data_dir)

    @app.get("/api/tailorings/{tid}/{kind}.pdf", include_in_schema=False)
    def tailoring_pdf(tid: int, kind: str, session: Session = Depends(get_session)):
        if kind not in TAILOR_KINDS:
            raise HTTPException(404)
        t, job = _get_tailoring(session, tid)
        return FileResponse(_tailoring_file(t, f"{kind}.pdf"), media_type="application/pdf",
                            filename=download_name(kind, job.company), content_disposition_type="inline",
                            headers=IMMUTABLE)

    @app.get("/api/tailorings/{tid}/pages/{kind}/{n}.png", include_in_schema=False)
    def tailoring_page(tid: int, kind: str, n: int, session: Session = Depends(get_session)):
        if kind not in TAILOR_KINDS or n < 1:
            raise HTTPException(404)
        t, _ = _get_tailoring(session, tid)
        return FileResponse(_tailoring_file(t, f"{kind}-{n}.png"), media_type="image/png", headers=IMMUTABLE)

    @app.post("/api/tailorings/{tid}/send", response_model=SendOut, dependencies=write)
    def send_tailoring_route(tid: int, session: Session = Depends(get_session)):
        t, job = _get_tailoring(session, tid)
        if t.status != "done":
            raise HTTPException(409, "tailoring is not finished")
        try:
            send_tailoring(session, t, job, Notifier(env.openclaw_bin, env.telegram_target))
        except NotifyError as e:
            raise HTTPException(502, str(e)) from e
        except (ValueError, OSError) as e:
            raise HTTPException(409, str(e)) from e
        return SendOut(sent=True, sent_at=t.sent_at)

    def _current_hash(requested: str | None) -> tuple[str | None, str | None]:
        if requested:
            return requested, None
        latex_dir = get_env().latex_dir
        if not (latex_dir / "resume.tex").is_file():
            return None, f"resume sources not found at {latex_dir}"
        return latex_hash(latex_dir), None

    @app.get("/api/resume/current", response_model=ResumeCurrentOut)
    def resume_current(hash: str | None = None):
        resume_hash, error = _current_hash(hash)
        out = _current_out(env.data_dir, resume_hash, error)
        if not out.ready and resume_hash and not hash and not error:
            now = time.monotonic()
            if now - preview_spawned.get(resume_hash, -PREVIEW_RESPAWN_SECONDS) >= PREVIEW_RESPAWN_SECONDS:
                preview_spawned[resume_hash] = now
                _spawn_cli("resume-preview")
        return out

    def _current_file(hash: str | None, name: str) -> FileResponse:
        resume_hash, _ = _current_hash(hash)
        meta = read_current(env.data_dir, resume_hash) if resume_hash else None
        if not meta:
            raise HTTPException(404, "current resume preview not built")
        path = current_dir(env.data_dir, meta["hash"]) / name
        if not path.is_file():
            raise HTTPException(404, "file not found")
        media = "application/pdf" if name.endswith(".pdf") else "image/png"
        headers = IMMUTABLE if hash else NO_CACHE
        if media == "application/pdf":
            return FileResponse(path, media_type=media, filename="Book_Sam_Resume.pdf",
                                content_disposition_type="inline", headers=headers)
        return FileResponse(path, media_type=media, headers=headers)

    @app.get("/api/resume/current.pdf", include_in_schema=False)
    def resume_current_pdf(hash: str | None = None):
        return _current_file(hash, "resume.pdf")

    @app.get("/api/resume/current/pages/{n}.png", include_in_schema=False)
    def resume_current_page(n: int, hash: str | None = None):
        if n < 1:
            raise HTTPException(404)
        return _current_file(hash, f"resume-{n}.png")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        static = env.static_dir.resolve()
        index = static / "index.html"
        target = index
        try:
            candidate = (static / path).resolve()
            if path and static in candidate.parents and candidate.is_file():
                target = candidate
        except (ValueError, OSError):
            target = index
        if target is index and not index.exists():
            raise HTTPException(404, "frontend not built")
        response = FileResponse(target)
        response.headers.update(SPA_SECURITY_HEADERS)
        return response

    return app
