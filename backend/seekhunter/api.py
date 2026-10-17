import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from seekhunter import repo
from seekhunter.config import get_env
from seekhunter.contacts import linkedin_search_urls
from seekhunter.db import get_session, init_db
from seekhunter.models import Job, JobEvaluation, Run, SearchProfile, Tailoring, utcnow
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


class JobOut(BaseModel):
    id: int
    source: str
    title: str
    company: str
    location: str
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


class JobDetailOut(JobOut):
    description_html: str
    teaser: str


class JobPatch(BaseModel):
    status: str | None = None
    notes: str | None = None


class UnexcludeIn(BaseModel):
    allowlist_employer: bool = False


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


def _job_out(job: Job, ev: JobEvaluation, detail: bool = False) -> JobOut:
    base = dict(
        id=job.id, source=job.source, title=job.title, company=job.company, location=job.location,
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
        insights_checked_at=job.insights_checked_at,
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

    @app.get("/api/jobs", response_model=list[JobOut])
    def list_jobs(view: str = "active", status: str | None = None, work_type: str | None = None,
                  source: str | None = None, q: str | None = None, limit: int = Query(200, ge=1, le=500),
                  offset: int = Query(0, ge=0), session: Session = Depends(get_session)):
        rows = repo.list_jobs(session, view=view, status=status, work_type=work_type, source=source, q=q,
                              limit=limit, offset=offset)
        return [_job_out(j, e) for j, e in rows]

    @app.get("/api/jobs/{job_id}", response_model=JobDetailOut)
    def get_job(job_id: int, session: Session = Depends(get_session)):
        return _job_out(*_get_job(session, job_id), detail=True)

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
        return _job_out(job, ev)

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
        return _job_out(job, ev)

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
        repo.save_settings(session, body)
        return body

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
