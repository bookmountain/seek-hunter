import subprocess
import sys
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from seekhunter import repo
from seekhunter.config import get_env
from seekhunter.db import get_session, init_db
from seekhunter.models import Job, JobEvaluation, Run, SearchProfile
from seekhunter.notify import Notifier, NotifyError
from seekhunter.security import ip_allowlist_middleware, require_write
from seekhunter.settings_model import AppSettings


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
    if init:
        init_db()
        from seekhunter.db import get_engine

        with Session(get_engine()) as s:
            repo.ensure_seed(s)

    app = FastAPI(title="SeekHunter")
    app.middleware("http")(ip_allowlist_middleware)
    write = [Depends(require_write)]

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/jobs", response_model=list[JobOut])
    def list_jobs(view: str = "active", status: str | None = None, work_type: str | None = None,
                  source: str | None = None, q: str | None = None, limit: int = 200, offset: int = 0,
                  session: Session = Depends(get_session)):
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
            if job.company not in settings.employer_allowlist:
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

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        static = env.static_dir.resolve()
        candidate = (static / path).resolve()
        if path and candidate.is_file() and static in candidate.parents:
            return FileResponse(candidate)
        index = static / "index.html"
        if not index.exists():
            raise HTTPException(404, "frontend not built")
        return FileResponse(index)

    return app
