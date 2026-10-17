"""End-to-end tailoring run for one `Tailoring` row: parse resume -> LLM -> validate -> compile -> send."""

import logging
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlmodel import Session

from seekhunter import repo
from seekhunter.config import Env
from seekhunter.models import Job, Tailoring, utcnow
from seekhunter.notify import NotifyError
from seekhunter.resume_doc import load_resume_doc
from seekhunter.tailor import current
from seekhunter.tailor.engine import LLM, JobContext, tailor
from seekhunter.tailor.render import Compiler, build_tailored

log = logging.getLogger(__name__)
ADELAIDE = ZoneInfo("Australia/Adelaide")
ERROR_LIMIT = 4000


class FileNotifier(Protocol):
    def send(self, text: str) -> None: ...

    def send_file(self, path: Path, caption: str) -> None: ...


def tailored_dir(env: Env, tailoring_id: int) -> Path:
    return env.data_dir / "tailored" / str(tailoring_id)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:40] or "Job"


def download_name(kind: str, company: str) -> str:
    label = "Resume" if kind == "resume" else "Cover_Letter"
    return f"Book_Sam_{label}_{_slug(company)}.pdf"


def _progress(session: Session, t: Tailoring, text: str) -> None:
    t.progress = text
    repo.save_tailoring(session, t)


def send_tailoring(session: Session, t: Tailoring, job: Job, notifier: FileNotifier) -> None:
    """Deliver both PDFs to Telegram as documents; sets `sent_at`. Raises NotifyError/ValueError."""
    if t.status != "done" or not t.out_dir:
        raise ValueError("tailoring is not finished")
    out = Path(t.out_dir)
    send_dir = out / "send"
    send_dir.mkdir(exist_ok=True)
    head = f"#{job.id} {job.title} — {job.company}"
    for kind, caption in (("resume", f"#{job.id} Tailored resume — {job.title} @ {job.company}"),
                          ("cover_letter", f"Cover letter — {head}")):
        named = send_dir / download_name(kind, job.company)
        shutil.copyfile(out / f"{kind}.pdf", named)
        notifier.send_file(named, caption)
    t.sent_at = utcnow()
    repo.save_tailoring(session, t)


def run_tailoring(session: Session, tailoring_id: int, *, env: Env, llm: LLM, compiler: Compiler,
                  notifier: FileNotifier | None = None, provider: str = "openclaw",
                  today: date | None = None) -> Tailoring:
    t = session.get(Tailoring, tailoring_id)
    if t is None:
        raise ValueError(f"tailoring {tailoring_id} not found")
    job = session.get(Job, t.job_id)
    if job is None:
        raise ValueError(f"job {t.job_id} not found")
    t.status, t.started_at, t.error, t.provider = "running", utcnow(), None, provider
    t.warnings, t.result, t.finished_at = [], {}, None
    _progress(session, t, "Reading resume")
    try:
        doc = load_resume_doc(env.resume_dir)
        _progress(session, t, "Rendering current resume")
        base_info = current.ensure_current(env.latex_dir, env.data_dir, compiler)
        t.resume_hash = base_info["hash"]

        _progress(session, t, "Tailoring with AI")
        ctx = JobContext(title=job.title, company=job.company, location=job.location, work_type=job.work_type,
                         contact_name=job.contact_name, ad_text=repo.to_jobdata(job).text)
        validated = tailor(ctx, doc, llm)

        _progress(session, t, "Compiling PDFs")
        out = tailored_dir(env, t.id)
        rendered = build_tailored(
            env.latex_dir, env.resume_dir, validated.doc, validated.cover_letter, out, compiler,
            job_title=job.title, company=job.company, contact_name=job.contact_name, location=job.location,
            today=today or datetime.now(ADELAIDE).date())
        t.out_dir = str(out)
        t.warnings = validated.warnings + rendered["warnings"]
        t.result = {
            "base": doc.model_dump(), "tailored": validated.doc.model_dump(),
            "keywords_matched": validated.keywords_matched, "gaps": validated.gaps,
            "cover_letter": validated.cover_letter.model_dump(), "pages": rendered["pages"],
        }
        t.status, t.progress, t.finished_at = "done", "Done", utcnow()
        repo.save_tailoring(session, t)
    except Exception as e:  # noqa: BLE001 - every failure is recorded on the row for the UI
        log.exception("tailoring %s failed", tailoring_id)
        t.status, t.progress, t.finished_at = "failed", "Failed", utcnow()
        t.error = f"{type(e).__name__}: {e}"[:ERROR_LIMIT]
        repo.save_tailoring(session, t)
        session.refresh(t)
        if t.send_requested and notifier:
            try:
                notifier.send(f"Tailoring for #{job.id} {job.title} failed: {str(e)[:300]}")
            except NotifyError:
                log.warning("could not report tailoring failure to Telegram")
        return t

    session.refresh(t)  # the API may have set send_requested while we were running
    if t.send_requested and notifier:
        _progress(session, t, "Sending to Telegram")
        try:
            send_tailoring(session, t, job, notifier)
        except (NotifyError, OSError) as e:
            t.warnings = [*t.warnings, f"Telegram delivery failed: {e}"]
        t.progress = "Done"
        repo.save_tailoring(session, t)
    return t
