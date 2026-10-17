"""Best-effort Resume-Matcher analysis of a finished tailoring.

SeekHunter keeps doing the tailoring itself (exact-layout LaTeX PDFs). Resume-Matcher adds a second
opinion: its own LLM-tailored version, an ATS score, missing keywords, interview prep and an outreach
message. Nothing here may fail the tailoring: every error ends up in `result["resume_matcher"]`.

`result["resume_matcher"]` = {status: queued|running|done|failed|unavailable, started_at, finished_at,
error, warnings, rm_master_id, rm_job_id, rm_resume_id, ats_score, sub_scores, missing_keywords,
matched_keywords, injectable_keywords, recommendations, job_keywords, interview_prep, outreach_message}.
"""

import logging

from pydantic import NaiveDatetime
from sqlmodel import Field, Session, SQLModel, select

from seekhunter import ats_score, repo
from seekhunter.config import Env
from seekhunter.models import Job, Tailoring, utcnow
from seekhunter.resume_doc import ResumeDoc
from seekhunter.resume_matcher import ResumeMatcher, RMError
from seekhunter.tailor import current

log = logging.getLogger(__name__)
PROGRESS = "Analysing with Resume-Matcher"
ERROR_LIMIT = 2000
NOT_SIGNED_IN = ("Resume-Matcher has no AI provider configured. Open Resume-Matcher, sign in with "
                 "ChatGPT (Settings), then retry.")


class ResumeMatcherMaster(SQLModel, table=True):
    """Which RM master resume holds the current resume PDF for a given `latex/` content hash."""

    __tablename__ = "resume_matcher_masters"

    resume_hash: str = Field(primary_key=True)
    rm_resume_id: str
    created_at: NaiveDatetime = Field(default_factory=utcnow)


def sync_master(session: Session, env: Env, client: ResumeMatcher, resume_hash: str) -> str:
    """RM master resume id for `resume_hash`, uploading the cached current PDF (and making it RM's
    default master) only when this hash has no live master yet. Older SeekHunter masters are removed
    from RM afterwards so its five-master limit is never hit."""
    row = session.get(ResumeMatcherMaster, resume_hash)
    if row:
        live = {r.get("resume_id") for r in client.list_resumes(include_master=True)}
        if row.rm_resume_id in live:
            return row.rm_resume_id
        session.delete(row)
        session.commit()

    if not current.read_current(env.data_dir, resume_hash):
        raise RMError("the current resume PDF is not built yet")
    pdf = current.current_dir(env.data_dir, resume_hash) / "resume.pdf"
    up = client.upload_resume(pdf, "Book_Sam_Resume.pdf")
    rid = up.get("resume_id")
    if not rid:
        raise RMError("Resume-Matcher upload returned no resume id")
    if up.get("processing_status") != "ready":
        try:
            client.delete_resume(rid)
        except RMError:
            log.warning("could not delete unparsed RM resume %s", rid)
        raise RMError(f"Resume-Matcher could not parse the resume (processing_status="
                      f"{up.get('processing_status')!r}); is its AI provider signed in?")
    client.set_default(rid)

    for old in session.exec(select(ResumeMatcherMaster)).all():
        try:
            client.delete_resume(old.rm_resume_id)
        except RMError as e:
            if e.status != 404:
                log.warning("could not delete old RM master %s: %s", old.rm_resume_id, e)
        session.delete(old)
    session.add(ResumeMatcherMaster(resume_hash=resume_hash, rm_resume_id=rid))
    session.commit()
    return rid


def _save(session: Session, t: Tailoring, rm: dict, **extra) -> None:
    t.result = {**(t.result or {}), "resume_matcher": dict(rm), **extra}  # new dict: JSON column change
    repo.save_tailoring(session, t)


def mark_queued(session: Session, t: Tailoring) -> None:
    _save(session, t, {"status": "queued", "error": None, "warnings": []})


def _ad_text(job: Job) -> str:
    head = "\n".join(x for x in (job.title, job.company, job.location) if x)
    return f"{head}\n\n{repo.to_jobdata(job).text}".strip()


def _rescored_ats(t: Tailoring, env: Env, job_keywords: dict) -> dict | None:
    result = t.result or {}
    if not result.get("base") or not result.get("tailored"):
        return None
    contact = ats_score.contact_from_latex(env.latex_dir)
    base, tailored = (ResumeDoc.model_validate(result[k]) for k in ("base", "tailored"))
    return {"keywords_source": "resume_matcher",
            "current": ats_score.score_doc(base, job_keywords, contact),
            "tailored": ats_score.score_doc(tailored, job_keywords, contact)}


def _analyse(session: Session, t: Tailoring, job: Job, env: Env, client: ResumeMatcher, rm: dict) -> dict:
    """The RM calls proper; mutates `rm` as it goes. Returns extra result keys (re-scored "ats")."""
    st = client.status()
    if not st.get("llm_configured"):
        rm.update(status="unavailable", error=NOT_SIGNED_IN)
        return {}
    if not t.resume_hash:
        raise RMError("tailoring has no resume hash")
    master = sync_master(session, env, client, t.resume_hash)
    rm["rm_master_id"] = master
    rm["rm_job_id"] = job_id = client.upload_job(_ad_text(job), master)
    _save(session, t, rm)

    data = client.improve(master, job_id)
    rm["rm_resume_id"] = tailored_id = data.get("resume_id")
    if not tailored_id:
        raise RMError("Resume-Matcher improve returned no tailored resume id")
    rm["warnings"] += list(data.get("warnings") or [])

    record = None
    try:
        record = client.ats_score(tailored_id)
    except RMError as e:
        rm["warnings"].append(f"ATS score fetch failed: {e}")
    score = (record or {}).get("score") or data.get("ats_score") or {}
    rm["ats_score"] = score.get("overall_score")
    rm["sub_scores"] = score.get("sub_scores") or {}
    rm["missing_keywords"] = list(score.get("missing_keywords") or [])
    rm["injectable_keywords"] = list(score.get("injectable_keywords") or [])
    rm["recommendations"] = list(score.get("recommendations") or [])

    job_keywords = None
    try:
        job_keywords = client.get_job(job_id).get("job_keywords") or None
    except RMError as e:
        rm["warnings"].append(f"Job keywords fetch failed: {e}")
    rm["job_keywords"] = job_keywords
    if job_keywords:
        preview = data.get("resume_preview") or {}
        rm["matched_keywords"] = ats_score.score_resume(preview, job_keywords)["matched_keywords"]

    rm["interview_prep"] = data.get("interview_prep") or None
    if not rm["interview_prep"]:
        try:
            rm["interview_prep"] = client.interview_prep(tailored_id) or None
        except RMError as e:
            rm["warnings"].append(f"Interview prep failed: {e}")
    rm["outreach_message"] = data.get("outreach_message") or None
    if not rm["outreach_message"]:
        try:
            rm["outreach_message"] = client.outreach(tailored_id) or None
        except RMError as e:
            rm["warnings"].append(f"Outreach message failed: {e}")

    rm.update(status="done", error=None)
    ats = _rescored_ats(t, env, job_keywords) if job_keywords else None
    return {"ats": ats} if ats else {}


def run_resume_matcher(session: Session, tailoring_id: int, *, env: Env, client: ResumeMatcher) -> Tailoring:
    """Run (or re-run) the RM analysis for a finished tailoring. Never raises for RM problems."""
    t = session.get(Tailoring, tailoring_id)
    if t is None or t.status != "done":
        raise ValueError(f"tailoring {tailoring_id} is not finished")
    job = session.get(Job, t.job_id)
    if job is None:
        raise ValueError(f"job {t.job_id} not found")
    rm: dict = {"status": "running", "started_at": utcnow().isoformat(), "finished_at": None, "error": None,
                "warnings": [], "rm_master_id": None, "rm_job_id": None, "rm_resume_id": None,
                "ats_score": None, "sub_scores": {}, "missing_keywords": [], "matched_keywords": [],
                "injectable_keywords": [], "recommendations": [], "job_keywords": None,
                "interview_prep": None, "outreach_message": None}
    previous_progress = t.progress
    t.progress = PROGRESS
    _save(session, t, rm)
    extra: dict = {}
    try:
        extra = _analyse(session, t, job, env, client, rm)
    except Exception as e:  # noqa: BLE001 - best effort: recorded for the UI, tailoring stays done
        log.warning("Resume-Matcher step for tailoring %s failed: %s", tailoring_id, e)
        session.rollback()  # a failed flush must not poison the final save below
        rm.update(status="failed", error=f"{type(e).__name__}: {e}"[:ERROR_LIMIT])
    rm["finished_at"] = utcnow().isoformat()
    t.progress = previous_progress if previous_progress != PROGRESS else "Done"
    _save(session, t, rm, **extra)
    return t
