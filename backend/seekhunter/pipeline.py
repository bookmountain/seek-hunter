import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session

from seekhunter import market, repo
from seekhunter.contacts import extract_contacts, is_plausible_name, normalize_phone
from seekhunter.domain import JobData, company_key
from seekhunter.filters import evaluate_exclusions
from seekhunter.http import SourceBlocked
from seekhunter.llm.base import LLMJobInput
from seekhunter.models import Application, Job, JobEvaluation, Outbox, Run, utcnow
from seekhunter.notify import DigestItem, NotifyError, format_digest, format_market_brief, format_recap
from seekhunter.profile import Profile, load_profile
from seekhunter.scoring import blend, score_job

log = logging.getLogger(__name__)
TZ = ZoneInfo("Australia/Adelaide")
LLM_BATCH = 8
LINKEDIN_LOOKUP_CAP = 25
BACKFILL_LINKEDIN_LOOKUP_CAP = 60


@dataclass
class RunReport:
    run_id: int
    new_jobs: int
    notified: int
    source_status: dict = field(default_factory=dict)


def _local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)


def digest_item(job: Job, ev: JobEvaluation, prior_application: Application | None = None,
                now: datetime | None = None) -> DigestItem:
    already_title = already_days = None
    if prior_application is not None:
        already_title = prior_application.title
        already_days = ((now or utcnow()) - prior_application.applied_at).days
    return DigestItem(job_id=job.id, score=ev.final_score, title=job.title, company=job.company,
                      location=job.location, work_type=job.work_type, matched=ev.matched_skills,
                      why=ev.llm_note, url=job.url, flags=ev.flags, contact_name=job.contact_name,
                      contact_phone=job.contact_phone, contact_email=job.contact_email,
                      applicant_count=job.applicant_count, already_applied_title=already_title,
                      already_applied_days_ago=already_days)


def _prior_application_for(apps_by_key: dict[str, list[Application]], job: Job) -> Application | None:
    """The most recent application for this job's company, excluding the job's own application
    (if any) — "this company already has my resume" for the digest/recap."""
    for a in apps_by_key.get(company_key(job.company), []):
        if a.job_id != job.id:
            return a
    return None


def _digest_items(session: Session, rows: list[tuple[Job, JobEvaluation]],
                  now: datetime) -> list[DigestItem]:
    keys = {company_key(j.company) for j, _ in rows}
    apps_by_key = repo.applications_by_company_keys(session, keys)
    return [digest_item(j, e, _prior_application_for(apps_by_key, j), now) for j, e in rows]


def _upsert_recruiter_contact(session: Session, job: Job) -> None:
    """Upserts the job's recruiter (when a name is known; phone-only contacts stay on the job) into
    `contacts`, linked to this job via `contact_jobs`."""
    if not job.contact_name:
        return
    contact = repo.upsert_contact(session, name=job.contact_name, company=job.company, role="Recruiter",
                                  phone=job.contact_phone, email=job.contact_email,
                                  linkedin=job.contact_linkedin)
    repo.link_contact_job(session, contact.id, job.id)


def _apply_contacts(session: Session, job: Job) -> None:
    """Fill contact_name/phone/email from the job's own ad text, preferring structured source data
    (already on `job` via `update_job_details`) over regex extraction for phone/email."""
    extracted = extract_contacts(repo.to_jobdata(job).text)
    name = extracted.name if is_plausible_name(extracted.name, job.title, job.company) else None
    repo.set_contacts(session, job, name=name, phone=normalize_phone(job.contact_phone or extracted.phone),
                      email=job.contact_email or extracted.email)
    _upsert_recruiter_contact(session, job)


def _lookup_linkedin(session: Session, jobs: list[Job],
                     contact_lookup: Callable[[str, str], str | None], cap: int) -> None:
    done = 0
    for job in jobs:
        if done >= cap:
            break
        if job.canonical_job_id or not job.contact_name or job.contact_linkedin:
            continue
        done += 1
        try:
            url = contact_lookup(job.contact_name, job.company)
        except Exception as e:  # noqa: BLE001  a bad lookup must not abort the run
            log.warning("linkedin lookup failed for job %s: %s", job.id, e)
            continue
        if url:
            repo.set_contacts(session, job, linkedin=url)
            _upsert_recruiter_contact(session, job)


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


def _jobdata_insights(data: JobData) -> dict:
    fields = ("applicant_count", "applicant_volume", "resume_pct", "cover_letter_pct")
    return {f: getattr(data, f) for f in fields if getattr(data, f) is not None}


def _apply_details(session: Session, name: str, source, job: Job, data: JobData) -> None:  # noqa: ANN001
    """Fetches and persists a job's detail page: description/contacts, and for SEEK, applicant
    insights too (SeekSource.details() now returns them in the same GraphQL request)."""
    details = source.details(data)
    repo.update_job_details(session, job, details)
    _apply_contacts(session, job)
    if name == "seek":
        repo.set_insights(session, job, _jobdata_insights(details), utcnow())


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
                        other = session.get(Job, dup)
                        if job.source == "seek" and other is not None and other.source != "seek":
                            # SEEK is canonical: reverse the link instead of folding the seek job
                            # into the older jora row.
                            other.canonical_job_id = job.id
                            if other.notified_at and not job.notified_at:
                                job.notified_at = other.notified_at
                            session.add(other)
                            session.add(job)
                            session.commit()
                            repo.delete_evaluation(session, other.id)
                            try:
                                _apply_details(session, name, source, job, data)
                            except Exception as e:  # noqa: BLE001  one bad detail page mustn't abort the rest
                                session.rollback()
                                log.warning("details failed for %s %s: %s", name, data.external_id, e)
                                st["error"] = f"details: {e}"
                            continue
                        job.canonical_job_id = dup
                        session.add(job)
                        session.commit()
                        continue
                    try:
                        _apply_details(session, name, source, job, data)
                    except Exception as e:  # noqa: BLE001  one bad detail page must not abort the source
                        session.rollback()
                        log.warning("details failed for %s %s: %s", name, data.external_id, e)
                        st["error"] = f"details: {e}"
        except SourceBlocked as e:
            session.rollback()
            st["status"], st["error"] = "degraded", str(e)
        except Exception as e:  # parsing or network errors must not kill the other sources
            session.rollback()
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
        for job, d, sr in batch:
            s = scores.get(str(job.id))
            if s:
                repo.save_evaluation(session, job.id, llm_score=s.fit, llm_note=s.why, llm_provider=provider,
                                     final_score=blend(sr.rule_score, s.fit))
                # LLM-supplied name is only trusted when it appears verbatim in the ad text, to
                # avoid storing a hallucinated name.
                if not job.contact_name and s.contact_name and s.contact_name in d.text:
                    repo.set_contacts(session, job, name=s.contact_name)
                    _upsert_recruiter_contact(session, job)
    return used


def run_insights_refresh(session: Session, seek_source, limit: int = 30) -> dict:  # noqa: ANN001
    """Refreshes SEEK applicant insights for up to `limit` eligible jobs (see
    `repo.jobs_needing_insights`). A `SourceBlocked` from the source stops the loop early (SEEK is
    rate-limiting us this run); any other per-job error is logged and skipped so one bad job
    doesn't block the rest."""
    jobs = repo.jobs_needing_insights(session, utcnow(), limit)
    refreshed = 0
    error = None
    for job in jobs:
        try:
            data = seek_source.insights(job.external_id)
        except SourceBlocked as e:
            error = str(e)
            break
        except Exception as e:  # noqa: BLE001  one bad lookup must not abort the refresh
            log.warning("insights refresh failed for seek %s: %s", job.external_id, e)
            continue
        repo.set_insights(session, job, data, utcnow())
        refreshed += 1
    return {"checked": len(jobs), "refreshed": refreshed, "error": error}


def _refresh_insights(session: Session, sources: dict, status: dict, settings) -> None:  # noqa: ANN001
    seek_source = sources.get("seek")
    if not seek_source:
        return
    report = run_insights_refresh(session, seek_source, settings.max_insights_per_run)
    seek_status = status.setdefault("seek", {})
    seek_status["insights_refreshed"] = report["refreshed"]
    if report["error"]:
        seek_status["insights_error"] = report["error"]


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
    _send(session, notifier, f"SeekHunter: all sources failing for 3 runs. {errors}")
    session.add(Run(kind="alert", finished_at=utcnow()))
    session.commit()


def run_crawl(session: Session, sources: dict, llm, notifier, profile: Profile, public_url: str,  # noqa: ANN001
             dry_run: bool = False,
             contact_lookup: Callable[[str, str], str | None] | None = None) -> RunReport:
    """Crawl, evaluate, and notify.

    Notification is at-least-once, not exactly-once: digest messages are sent via the notifier
    *before* `repo.mark_notified` runs, and a send failure is parked in the outbox (flushed on the
    next run) rather than silently dropped. A crash between sending and `mark_notified` can
    therefore resend a job on the next run, but a job is never silently skipped.

    `contact_lookup(name, company) -> url | None` is an optional LinkedIn-profile lookup (e.g. Brave
    Search), called at most `LINKEDIN_LOOKUP_CAP` times per run for new jobs with a contact name.
    """
    settings = repo.load_settings(session)
    run = Run(kind="crawl")
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        if not dry_run:
            _flush_outbox(session, notifier)
        new_jobs, status = _collect(session, sources, settings)
        run.source_status, run.new_jobs = status, len(new_jobs)

        # Recover jobs a crashed earlier run upserted but never evaluated.
        seen_ids = {j.id for j in new_jobs}
        recovered = [j for j in repo.unevaluated_jobs(session) if j.id not in seen_ids]
        run.llm_provider = _evaluate(session, new_jobs + recovered, profile, settings, llm)

        if contact_lookup:
            _lookup_linkedin(session, new_jobs + recovered, contact_lookup, LINKEDIN_LOOKUP_CAP)

        _refresh_insights(session, sources, status, settings)
        # `status` is mutated in place above; an autoflush earlier in this transaction may already
        # have persisted its pre-mutation content and left the JSON attribute looking "unchanged"
        # (same dict object, so a plain re-assignment is a no-op to SQLAlchemy's dirty tracking).
        # flag_modified forces it back into the next flush regardless.
        run.source_status = status
        flag_modified(run, "source_status")

        now = utcnow()
        candidates = repo.notification_candidates(session, now)
        if candidates and settings.notify_enabled:
            top = candidates[: settings.max_notify_per_run]
            degraded = [k for k, v in status.items() if v["status"] != "ok"]
            for text in format_digest(_digest_items(session, top, now), _local(now), public_url, degraded,
                                      extra=len(candidates) - len(top)):
                _send(session, notifier, text)
            run.notified = len(top)
        # Intentionally marks candidates notified even when notify_enabled is False, so that
        # re-enabling notifications later doesn't flood Telegram with a backlog of old jobs.
        # Skipped during a dry run, which must have no side effects.
        if candidates and not dry_run:
            repo.mark_notified(session, [j.id for j, _ in candidates], now)
    except Exception as e:
        session.rollback()
        run.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        run.finished_at = utcnow()
        session.add(run)
        session.commit()
    if not dry_run:
        _maybe_health_alert(session, notifier, run)
    return RunReport(run_id=run.id, new_jobs=run.new_jobs, notified=run.notified,
                     source_status=run.source_status)


def run_recap(session: Session, notifier, public_url: str, dry_run: bool = False) -> None:  # noqa: ANN001
    settings = repo.load_settings(session)
    if not settings.recap_enabled:
        return
    local_now = _local(utcnow())
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    rows = repo.list_jobs(session, view="active", since=since, limit=500)
    excluded = repo.count_excluded_since(session, since)
    now = utcnow()
    due = repo.follow_ups_due(session, now)[:3]
    follow_ups = [{"company": a.company, "title": a.title, "days": (now - a.applied_at).days} for a in due]
    for text in format_recap(_digest_items(session, rows, now), excluded, f"{local_now:%a %d %b}",
                             public_url, follow_ups=follow_ups or None):
        _send(session, notifier, text)
    if not dry_run:
        session.add(Run(kind="recap", finished_at=utcnow(), new_jobs=len(rows)))
        session.commit()


def run_insights_brief(session: Session, notifier, public_url: str, resume_dir: Path,  # noqa: ANN001
                       dry_run: bool = False) -> None:
    """Weekly market-insights brief (plain text): per-city totals/flexible share, Adelaide's top
    skills, biggest gaps, a head-to-head line, and the best city for flexible roles."""
    overview_rows = market.overview(session, days=14)
    try:
        profile_skills = load_profile(resume_dir).skills
    except FileNotFoundError:
        profile_skills = set()
    top_skills = market.skill_demand(session, "adelaide", days=14, profile_skills=profile_skills, top=5)
    top_gaps = market.gaps(session, "adelaide", days=14, profile_skills=profile_skills, top=3)

    pair_skills = sorted({s for pair in market.HEAD_TO_HEAD_PAIRS for s in pair})
    shares_by_city = {row["city"]: row["shares"] for row in market.compare(session, pair_skills, days=14)}
    best = max(overview_rows, key=lambda r: r["flexible_share"], default=None)
    best_city = best["city"] if best else "adelaide"
    best_share = best["flexible_share"] if best else 0.0
    h2h = market.head_to_head_lines(shares_by_city.get("adelaide", {}), best_city,
                                    shares_by_city.get(best_city, {}))

    text = format_market_brief(overview_rows, top_skills, top_gaps, h2h, best_city, best_share, public_url)
    _send(session, notifier, text)
    if not dry_run:
        session.add(Run(kind="insights_brief", finished_at=utcnow()))
        session.commit()


def run_rescore(session: Session, profile: Profile, days: int = 7) -> int:
    settings = repo.load_settings(session)
    count = 0
    for job in repo.jobs_since(session, utcnow() - timedelta(days=days)):
        data = repo.to_jobdata(job)
        fr = evaluate_exclusions(data, settings)
        sr = score_job(data, profile.skills, settings)
        existing = repo.get_evaluation(session, job.id)
        llm_score = existing.llm_score if existing else None
        repo.save_evaluation(session, job.id, excluded=fr.excluded, reasons=fr.reasons, snippets=fr.snippets,
                             rule_score=sr.rule_score, final_score=blend(sr.rule_score, llm_score),
                             matched_skills=sr.matched_skills, flags=sr.flags)
        count += 1
    session.add(Run(kind="rescore", finished_at=utcnow(), new_jobs=count))
    session.commit()
    return count


def run_contacts_backfill(session: Session, seek_source, contact_lookup=None,  # noqa: ANN001
                          days: int = 7) -> dict:
    """Backfill recruiter contacts for jobs first seen in the last `days` days.

    For every such job, re-runs `extract_contacts` on the stored ad text. SEEK jobs still missing a
    phone or email are re-fetched via `seek_source.details()` to pick up `contactMatches`. If
    `contact_lookup` is given, looks up a LinkedIn profile for jobs that have a contact name but no
    LinkedIn URL yet, capped at `BACKFILL_LINKEDIN_LOOKUP_CAP` lookups.
    """
    jobs = repo.jobs_since(session, utcnow() - timedelta(days=days))
    updated = 0
    for job in jobs:
        if job.source == "seek" and (not job.contact_phone or not job.contact_email):
            try:
                refreshed = seek_source.details(repo.to_jobdata(job))
            except Exception as e:  # noqa: BLE001  a bad detail fetch must not abort the backfill
                log.warning("contacts backfill: details failed for seek %s: %s", job.external_id, e)
            else:
                job.contact_phone = job.contact_phone or refreshed.contact_phone
                job.contact_email = job.contact_email or refreshed.contact_email
                if refreshed.description_html:
                    job.description_html = refreshed.description_html
                session.add(job)
                session.commit()

        extracted = extract_contacts(repo.to_jobdata(job).text)
        # Re-derive the name from scratch with the current extractor (drops names an older,
        # looser extractor stored); an LLM-supplied name is kept only if it still passes the checks.
        name = extracted.name if is_plausible_name(extracted.name, job.title, job.company) else None
        phone = normalize_phone(job.contact_phone or extracted.phone)
        email = job.contact_email or extracted.email
        if (name, phone, email) != (job.contact_name, job.contact_phone, job.contact_email):
            updated += 1
        if name != job.contact_name:
            job.contact_name = name  # may clear a name stored by an older, looser extractor
            job.contact_linkedin = None
        repo.set_contacts(session, job, name=name, phone=phone, email=email)
        _upsert_recruiter_contact(session, job)

    linkedin_lookups = linkedin_found = 0
    if contact_lookup:
        for job in jobs:
            if linkedin_lookups >= BACKFILL_LINKEDIN_LOOKUP_CAP:
                break
            if job.canonical_job_id or not job.contact_name or job.contact_linkedin:
                continue
            linkedin_lookups += 1
            try:
                url = contact_lookup(job.contact_name, job.company)
            except Exception as e:  # noqa: BLE001  a bad lookup must not abort the backfill
                log.warning("linkedin lookup failed for job %s: %s", job.id, e)
                continue
            if url:
                linkedin_found += 1
                repo.set_contacts(session, job, linkedin=url)
                _upsert_recruiter_contact(session, job)

    return {"jobs_checked": len(jobs), "updated": updated, "linkedin_lookups": linkedin_lookups,
           "linkedin_found": linkedin_found}
