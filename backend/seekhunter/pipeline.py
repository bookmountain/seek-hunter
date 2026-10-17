import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session

from seekhunter import repo
from seekhunter.filters import evaluate_exclusions
from seekhunter.http import SourceBlocked
from seekhunter.llm.base import LLMJobInput
from seekhunter.models import Job, JobEvaluation, Outbox, Run, utcnow
from seekhunter.notify import DigestItem, NotifyError, format_digest, format_recap
from seekhunter.profile import Profile
from seekhunter.scoring import blend, score_job

log = logging.getLogger(__name__)
TZ = ZoneInfo("Australia/Adelaide")
LLM_BATCH = 8


@dataclass
class RunReport:
    run_id: int
    new_jobs: int
    notified: int
    source_status: dict = field(default_factory=dict)


def _local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)


def digest_item(job: Job, ev: JobEvaluation) -> DigestItem:
    return DigestItem(job_id=job.id, score=ev.final_score, title=job.title, company=job.company,
                      location=job.location, work_type=job.work_type, matched=ev.matched_skills,
                      why=ev.llm_note, url=job.url, flags=ev.flags)


def _send(session: Session, notifier, text: str) -> bool:  # noqa: ANN001
    try:
        notifier.send(text)
        return True
    except NotifyError as e:
        log.error("notify failed: %s", e)
        session.add(Outbox(text=text, attempts=1, last_error=str(e)))
        session.commit()
        return False


def _flush_outbox(session: Session, notifier) -> None:  # noqa: ANN001
    for msg in repo.pending_outbox(session):
        try:
            notifier.send(msg.text)
            msg.sent_at = utcnow()
        except NotifyError as e:
            msg.attempts += 1
            msg.last_error = str(e)
        session.add(msg)
        session.commit()


def _collect(session: Session, sources: dict, settings) -> tuple[list[Job], dict]:  # noqa: ANN001
    status: dict = {}
    new_jobs: list[Job] = []
    profiles = repo.list_search_profiles(session, enabled_only=True)
    for name, source in sources.items():
        st = {"status": "ok", "found": 0, "new": 0, "error": None}
        try:
            for profile in profiles:
                if name not in profile.sources:
                    continue
                for data in source.search(profile, settings.max_pages_per_search):
                    st["found"] += 1
                    job, is_new = repo.upsert_job(session, data)
                    if not is_new:
                        continue
                    st["new"] += 1
                    new_jobs.append(job)
                    dup = repo.find_duplicate(session, job)
                    if dup:
                        job.canonical_job_id = dup
                        session.add(job)
                        session.commit()
                        continue
                    try:
                        repo.update_job_details(session, job, source.details(data))
                    except Exception as e:  # noqa: BLE001  one bad detail page must not abort the source
                        log.warning("details failed for %s %s: %s", name, data.external_id, e)
                        st["error"] = f"details: {e}"
        except SourceBlocked as e:
            st["status"], st["error"] = "degraded", str(e)
        except Exception as e:  # parsing or network errors must not kill the other sources
            log.exception("source %s failed", name)
            st["status"], st["error"] = "degraded", f"{type(e).__name__}: {e}"
        st["requests"] = getattr(source.client, "request_count", 0)
        st["blocked"] = getattr(source.client, "blocked_count", 0)
        status[name] = st
    return new_jobs, status


def _evaluate(session: Session, jobs: list[Job], profile: Profile, settings, llm) -> str | None:  # noqa: ANN001
    pending: list[tuple[Job, object, object]] = []
    for job in jobs:
        if job.canonical_job_id:
            continue
        data = repo.to_jobdata(job)
        fr = evaluate_exclusions(data, settings)
        sr = score_job(data, profile.skills, settings)
        repo.save_evaluation(session, job.id, excluded=fr.excluded, reasons=fr.reasons, snippets=fr.snippets,
                             rule_score=sr.rule_score, llm_score=None, llm_note=None, llm_provider=None,
                             final_score=sr.rule_score, matched_skills=sr.matched_skills, flags=sr.flags)
        if not fr.excluded:
            pending.append((job, data, sr))

    used = None
    for i in range(0, len(pending), LLM_BATCH):
        batch = pending[i : i + LLM_BATCH]
        inputs = [LLMJobInput(key=str(j.id), title=d.title, company=d.company, work_type=d.work_type,
                              text=d.text) for j, d, _ in batch]
        scores, provider = llm.score_batch(profile, inputs)
        used = used or provider
        for job, _, sr in batch:
            s = scores.get(str(job.id))
            if s:
                repo.save_evaluation(session, job.id, llm_score=s.fit, llm_note=s.why, llm_provider=provider,
                                     final_score=blend(sr.rule_score, s.fit))
    return used


def _maybe_health_alert(session: Session, notifier, run: Run) -> None:  # noqa: ANN001
    recent = repo.recent_runs(session, "crawl", 3)
    if len(recent) < 3:
        return
    if not all(
        r.source_status and all(s["status"] != "ok" for s in r.source_status.values()) for r in recent
    ):
        return
    last_alert = repo.recent_runs(session, "alert", 1)
    if last_alert and last_alert[0].started_at > utcnow() - timedelta(hours=24):
        return
    errors = "; ".join(f"{k}: {v.get('error')}" for k, v in run.source_status.items())
    _send(session, notifier, f"⚠️ SeekHunter: all sources failing for 3 runs. {errors}")
    session.add(Run(kind="alert", finished_at=utcnow()))
    session.commit()


def run_crawl(session: Session, sources: dict, llm, notifier, profile: Profile, public_url: str) -> RunReport:  # noqa: ANN001
    settings = repo.load_settings(session)
    run = Run(kind="crawl")
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        _flush_outbox(session, notifier)
        new_jobs, status = _collect(session, sources, settings)
        run.source_status, run.new_jobs = status, len(new_jobs)

        # Recover jobs a crashed earlier run upserted but never evaluated.
        seen_ids = {j.id for j in new_jobs}
        recovered = [j for j in repo.unevaluated_jobs(session) if j.id not in seen_ids]
        run.llm_provider = _evaluate(session, new_jobs + recovered, profile, settings, llm)

        now = utcnow()
        candidates = repo.notification_candidates(session, now)
        if candidates and settings.notify_enabled:
            top = candidates[: settings.max_notify_per_run]
            degraded = [k for k, v in status.items() if v["status"] != "ok"]
            for text in format_digest([digest_item(j, e) for j, e in top], _local(now), public_url, degraded,
                                      extra=len(candidates) - len(top)):
                _send(session, notifier, text)
            run.notified = len(top)
        if candidates:
            repo.mark_notified(session, [j.id for j, _ in candidates], now)
    except Exception as e:
        run.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        run.finished_at = utcnow()
        session.add(run)
        session.commit()
    _maybe_health_alert(session, notifier, run)
    return RunReport(run_id=run.id, new_jobs=run.new_jobs, notified=run.notified,
                     source_status=run.source_status)


def run_recap(session: Session, notifier, public_url: str) -> None:  # noqa: ANN001
    settings = repo.load_settings(session)
    if not settings.recap_enabled:
        return
    local_now = _local(utcnow())
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    rows = repo.list_jobs(session, view="active", since=since)
    excluded = repo.count_excluded_since(session, since)
    for text in format_recap([digest_item(j, e) for j, e in rows], excluded, f"{local_now:%a %d %b}",
                             public_url):
        _send(session, notifier, text)
    session.add(Run(kind="recap", finished_at=utcnow(), new_jobs=len(rows)))
    session.commit()
