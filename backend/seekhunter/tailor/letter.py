"""Regenerates only the cover letter of a finished tailoring (the resume is left as it is).

`result["cover_letter_regen"]` = {status: queued|running|done|failed, started_at, finished_at, error,
version}; `version` counts finished regenerations and busts the browser cache of the letter's PDF/PNGs.
"""

import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlmodel import Session

from seekhunter import repo
from seekhunter.config import Env
from seekhunter.models import Job, Tailoring, utcnow
from seekhunter.resume_doc import ResumeDoc
from seekhunter.tailor.engine import LLM, JobContext, write_letter
from seekhunter.tailor.models import CoverLetter
from seekhunter.tailor.render import Compiler, build_letter

log = logging.getLogger(__name__)
ADELAIDE = ZoneInfo("Australia/Adelaide")
ERROR_LIMIT = 2000


def _save(session: Session, t: Tailoring, regen: dict, **extra) -> None:
    # A new dict, so SQLAlchemy sees the JSON column change.
    t.result = {**(t.result or {}), "cover_letter_regen": dict(regen), **extra}
    repo.save_tailoring(session, t)


def mark_queued(session: Session, t: Tailoring) -> None:
    prev = (t.result or {}).get("cover_letter_regen") or {}
    _save(session, t, {"status": "queued", "started_at": utcnow().isoformat(), "finished_at": None,
                       "error": None, "version": prev.get("version", 0)})


def run_letter_regen(session: Session, tailoring_id: int, *, env: Env, llm: LLM, compiler: Compiler,
                     today: date | None = None) -> Tailoring:
    """Write a new cover letter for the tailored resume and re-render it. Failures are recorded in
    `result["cover_letter_regen"]`; the previous letter stays in place."""
    t = session.get(Tailoring, tailoring_id)
    if t is None or t.status != "done" or not t.out_dir or not (t.result or {}).get("tailored"):
        raise ValueError(f"tailoring {tailoring_id} is not finished")
    job = session.get(Job, t.job_id)
    if job is None:
        raise ValueError(f"job {t.job_id} not found")
    result = t.result
    regen = {**(result.get("cover_letter_regen") or {}), "status": "running", "error": None,
             "started_at": utcnow().isoformat(), "finished_at": None}
    _save(session, t, regen)
    try:
        doc = ResumeDoc.model_validate(result["tailored"])
        phrases = result.get("target_phrases") or {}
        ctx = JobContext(title=job.title, company=job.company, location=job.location, work_type=job.work_type,
                         contact_name=job.contact_name, ad_text=repo.to_jobdata(job).text)
        previous = CoverLetter.model_validate(result.get("cover_letter") or {})
        letter, warnings = write_letter(ctx, doc, llm, previous=previous,
                                        supported=list(phrases.get("supported") or []),
                                        unsupported=list(phrases.get("unsupported") or []))
        rendered = build_letter(env.latex_dir, env.resume_dir, letter, Path(t.out_dir), compiler,
                                job_title=job.title, company=job.company, contact_name=job.contact_name,
                                location=job.location, today=today or datetime.now(ADELAIDE).date())
    except Exception as e:  # noqa: BLE001 - recorded on the row for the UI
        log.exception("cover letter regeneration for tailoring %s failed", tailoring_id)
        _save(session, t, {**regen, "status": "failed", "finished_at": utcnow().isoformat(),
                           "error": f"{type(e).__name__}: {e}"[:ERROR_LIMIT]})
        return t

    # Letter warnings all start with "Cover letter"; swap the old letter's for the new one's.
    kept = [w for w in (t.warnings or []) if not w.startswith("Cover letter")]
    t.warnings = kept + warnings + rendered["warnings"]
    _save(session, t, {**regen, "status": "done", "finished_at": utcnow().isoformat(),
                       "version": int(regen.get("version") or 0) + 1},
          cover_letter=letter.model_dump(),
          pages={**result.get("pages", {}), "cover_letter": rendered["pages"]})
    return t
