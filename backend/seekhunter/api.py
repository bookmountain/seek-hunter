import subprocess
import sys
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from seekhunter import repo
from seekhunter.config import get_env
from seekhunter.db import get_session, init_db
from seekhunter.models import Job, JobEvaluation, Run, SearchProfile, utcnow
from seekhunter.notify import Notifier, NotifyError, format_brief
from seekhunter.profile import load_profile
from seekhunter.security import ensure_safe_write_token, ip_allowlist_middleware, require_write
from seekhunter.settings_model import AppSettings
from seekhunter.skills import extract_skills

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


def _job_out(job: Job, ev: JobEvaluation, detail: bool = False) -> JobOut:
    base = dict(
        id=job.id, source=job.source, title=job.title, company=job.company, location=job.location,
        work_type=job.work_type, salary_label=job.salary_label, listed_at=job.listed_at,
        first_seen_at=job.first_seen_at, url=job.url, status=job.status, notes=job.notes,
        force_include=job.force_include, excluded=ev.excluded, reasons=ev.reasons, snippets=ev.snippets,
        rule_score=ev.rule_score, llm_score=ev.llm_score, llm_note=ev.llm_note, final_score=ev.final_score,
        matched_skills=ev.matched_skills, flags=ev.flags,
    )
    if detail:
        return JobDetailOut(**base, description_html=job.description_html, teaser=job.teaser)
    return JobOut(**base)


def _get_job(session: Session, job_id: int) -> tuple[Job, JobEvaluation]:
    job = session.get(Job, job_id)
    ev = session.exec(select(JobEvaluation).where(JobEvaluation.job_id == job_id)).first()
    if not job or not ev:
        raise HTTPException(404, "job not found")
    return job, ev


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
