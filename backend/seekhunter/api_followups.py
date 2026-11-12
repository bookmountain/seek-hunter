"""Recruiter call scripts, the follow-up loop and funnel stats (mounted by api.create_app)."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from seekhunter import call_script, followups, repo
from seekhunter.config import get_env
from seekhunter.db import get_session
from seekhunter.domain import is_agency
from seekhunter.funnel import funnel
from seekhunter.models import Job, utcnow
from seekhunter.resume_doc import ResumeDoc, load_resume_doc
from seekhunter.security import require_write

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["follow-ups"])
write = [Depends(require_write)]


class CallScriptOut(BaseModel):
    job_id: int
    questions: list[str]
    pitch: str
    source: str  # llm | template
    provider: str | None
    warnings: list[str]
    cached: bool
    created_at: datetime | None
    agency: bool


class FollowUpOut(BaseModel):
    key: str
    kind: str
    days: int
    since: datetime
    company: str
    title: str
    channel: str
    message: str
    subject: str | None
    hint: str | None
    application_id: int | None
    job_id: int | None
    contact_id: int | None
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    contact_linkedin: str | None
    link: str


class SnoozeIn(BaseModel):
    days: int = Field(default=3, ge=1, le=60)


class DoneIn(BaseModel):
    note: str = ""


class FunnelRowOut(BaseModel):
    label: str
    applied: int
    responded: int
    interview: int
    offer: int
    response_rate: float | None
    interview_rate: float | None


class FunnelOut(BaseModel):
    total: FunnelRowOut
    by_source: list[FunnelRowOut]
    by_employer: list[FunnelRowOut]
    by_work_type: list[FunnelRowOut]
    by_call: list[FunnelRowOut]


def _resume() -> ResumeDoc:
    try:
        return load_resume_doc(get_env().resume_dir)
    except FileNotFoundError:
        log.warning("resume dir missing; call script uses an empty profile")
        return ResumeDoc(summary="", skills=[], experiences=[], projects=[])


def _job(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


def _agency(session: Session, job: Job) -> bool:
    return is_agency(job.company, repo.load_settings(session).agency_keywords)


def _script_out(job_id: int, s: call_script.Script, *, cached: bool, created_at: datetime | None,
                agency: bool) -> CallScriptOut:
    return CallScriptOut(job_id=job_id, questions=s.questions, pitch=s.pitch, source=s.source,
                         provider=s.provider, warnings=s.warnings, cached=cached, created_at=created_at,
                         agency=agency)


@router.get("/jobs/{job_id}/call-script", response_model=CallScriptOut)
def get_call_script(job_id: int, session: Session = Depends(get_session)):
    """The cached script, else an instant template preview (not stored; POST generates + caches)."""
    job = _job(session, job_id)
    agency = _agency(session, job)
    row = call_script.cached(session, job_id)
    if row:
        s = call_script.Script(questions=row.questions, pitch=row.pitch, source=row.source,
                               provider=row.provider, warnings=row.warnings)
        return _script_out(job_id, s, cached=True, created_at=row.created_at, agency=agency)
    return _script_out(job_id, call_script.preview(job, _resume(), agency=agency), cached=False,
                       created_at=None, agency=agency)


@router.post("/jobs/{job_id}/call-script", response_model=CallScriptOut, dependencies=write)
def generate_call_script(job_id: int, refresh: bool = False, session: Session = Depends(get_session)):
    """Generate with the LLM (template fallback) and cache. Returns the cached LLM script unless
    `refresh`; a cached template script is always regenerated (the LLM may be back)."""
    job = _job(session, job_id)
    agency = _agency(session, job)
    row = call_script.cached(session, job_id)
    if row and not refresh and row.source == "llm":
        s = call_script.Script(questions=row.questions, pitch=row.pitch, source=row.source,
                               provider=row.provider, warnings=row.warnings)
        return _script_out(job_id, s, cached=True, created_at=row.created_at, agency=agency)
    llms = call_script.text_llms(repo.load_settings(session), get_env())
    script = call_script.generate(job, _resume(), agency=agency, llms=llms)
    row = call_script.save(session, job_id, script)
    return _script_out(job_id, script, cached=True, created_at=row.created_at, agency=agency)


@router.get("/follow-ups", response_model=list[FollowUpOut])
def list_follow_ups(session: Session = Depends(get_session)):
    return [FollowUpOut(**i.as_dict()) for i in followups.due(session)]


@router.get("/follow-ups/summary", response_class=PlainTextResponse)
def follow_ups_summary(session: Session = Depends(get_session)):
    now = utcnow()
    return followups.format_text(followups.due(session, now), now)


def _item(session: Session, key: str) -> followups.FollowUp:
    item = followups.find(session, key)
    if not item:
        raise HTTPException(404, "follow-up not found (already handled, or no longer due)")
    return item


@router.post("/follow-ups/{key}/snooze", status_code=204, dependencies=write)
def snooze_follow_up(key: str, body: SnoozeIn, session: Session = Depends(get_session)):
    followups.snooze(session, _item(session, key), body.days)


@router.post("/follow-ups/{key}/dismiss", status_code=204, dependencies=write)
def dismiss_follow_up(key: str, session: Session = Depends(get_session)):
    followups.dismiss(session, _item(session, key))


@router.post("/follow-ups/{key}/done", status_code=204, dependencies=write)
def done_follow_up(key: str, body: DoneIn, session: Session = Depends(get_session)):
    followups.mark_done(session, _item(session, key), body.note.strip())


@router.get("/funnel", response_model=FunnelOut)
def get_funnel(days: int | None = Query(None, ge=1, le=730), session: Session = Depends(get_session)):
    since = utcnow() - timedelta(days=days) if days else None
    return funnel(session, since)
