from datetime import timedelta

import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

from seekhunter import repo
from seekhunter.domain import JobData
from seekhunter.http import SourceBlocked
from seekhunter.llm.base import LLMScore
from seekhunter.lock import RunLocked, run_lock
from seekhunter.models import Contact, ContactJob, Job, JobEvaluation, Outbox, Run
from seekhunter.models import utcnow as _utcnow
from seekhunter.notify import NotifyError
from seekhunter.pipeline import (
    _lookup_linkedin,
    _max_pages_for,
    digest_item,
    run_contacts_backfill,
    run_crawl,
    run_insights_brief,
    run_insights_refresh,
    run_recap,
    run_rescore,
)
from seekhunter.profile import Profile

PROFILE = Profile(skills={"React", "TypeScript"}, summary="s", titles=[], skill_lines=[], bullets=[])


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.ensure_seed(s)
        for p in repo.list_search_profiles(s)[1:]:
            p.enabled = False
            s.add(p)
        s.commit()
        yield s


def jd(source, ext, title="React Developer", company="Acme", desc="React TypeScript", wt="contract",
      applicant_count=None, applicant_volume=None, resume_pct=None, cover_letter_pct=None):
    return JobData(source=source, external_id=ext, title=title, company=company, location="Adelaide SA",
                   work_type=wt, url=f"https://x/{source}/{ext}", description_html=f"<p>{desc}</p>",
                   applicant_count=applicant_count, applicant_volume=applicant_volume,
                   resume_pct=resume_pct, cover_letter_pct=cover_letter_pct)


class FakeSource:
    def __init__(self, name, jobs, blocked=False, insights_blocked=False):
        self.name, self.jobs, self.blocked = name, jobs, blocked
        self.insights_blocked = insights_blocked
        self.client = type("C", (), {"request_count": 0, "blocked_count": 0})()
        self.detail_calls = 0
        self.insights_calls = 0

    def search(self, profile, max_pages):
        if self.blocked:
            raise SourceBlocked("403")
        return [JobData(**{**j.__dict__, "description_html": ""}) for j in self.jobs]

    def insights(self, external_id):
        self.insights_calls += 1
        if self.insights_blocked:
            raise SourceBlocked("403")
        job = next((j for j in self.jobs if j.external_id == external_id), None)
        if job is None:
            return {}
        return {k: v for k, v in (
            ("applicant_count", job.applicant_count), ("applicant_volume", job.applicant_volume),
            ("resume_pct", job.resume_pct), ("cover_letter_pct", job.cover_letter_pct),
        ) if v is not None}

    def details(self, job):
        self.detail_calls += 1
        return next(j for j in self.jobs if j.external_id == job.external_id)


class FlakyDetailsSource(FakeSource):
    """Raises a non-SourceBlocked error on the first details() call only."""

    def details(self, job):
        self.detail_calls += 1
        if self.detail_calls == 1:
            raise ValueError("boom")
        return next(j for j in self.jobs if j.external_id == job.external_id)


class FakeChain:
    def score_batch(self, profile, jobs):
        return {j.key: LLMScore(fit=50, why="ok") for j in jobs}, "fake"


class FakeNotifier:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, text):
        if self.fail:
            raise NotifyError("down")
        self.sent.append(text)


def test_full_run_excludes_dedupes_scores_and_notifies(session):
    seek = FakeSource("seek", [jd("seek", "1"), jd("seek", "2", company="Westpac"),
                               jd("seek", "3", desc="NV1 clearance required")])
    jora = FakeSource("jora", [jd("jora", "a"), jd("jora", "b", title="Vue Developer", company="Other")])
    notifier = FakeNotifier()
    report = run_crawl(session, {"seek": seek, "jora": jora}, FakeChain(), notifier, PROFILE, "https://sh")

    assert report.new_jobs == 5
    evals = {e.job_id: e for e in session.exec(select(JobEvaluation)).all()}
    jobs = {(j.source, j.external_id): j for j in session.exec(select(Job)).all()}
    assert evals[jobs[("seek", "2")].id].reasons == ["bank"]
    assert evals[jobs[("seek", "3")].id].reasons == ["clearance"]
    assert jobs[("jora", "a")].canonical_job_id == jobs[("seek", "1")].id
    good = evals[jobs[("seek", "1")].id]
    assert good.llm_score == 50 and good.llm_provider == "fake"
    assert good.final_score == round(0.6 * good.rule_score + 0.4 * 50)
    assert len(notifier.sent) == 1 and "SeekHunter — 2 new" in notifier.sent[0]

    again = FakeNotifier()
    report2 = run_crawl(session, {"seek": seek, "jora": jora}, FakeChain(), again, PROFILE, "https://sh")
    assert report2.new_jobs == 0 and again.sent == []
    assert seek.detail_calls == 3


def test_blocked_source_is_degraded_and_others_continue(session):
    seek = FakeSource("seek", [jd("seek", "1")])
    jora = FakeSource("jora", [], blocked=True)
    notifier = FakeNotifier()
    report = run_crawl(session, {"seek": seek, "jora": jora}, FakeChain(), notifier, PROFILE, "https://sh")
    assert report.source_status["jora"]["status"] == "degraded"
    assert report.source_status["seek"]["status"] == "ok"
    assert "Jora unavailable this run" in notifier.sent[0]


def test_notify_failure_goes_to_outbox_and_flushes_next_run(session):
    seek = FakeSource("seek", [jd("seek", "1")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(fail=True), PROFILE, "https://sh")
    assert len(session.exec(select(Outbox)).all()) == 1
    ok = FakeNotifier()
    run_crawl(session, {"seek": seek}, FakeChain(), ok, PROFILE, "https://sh")
    assert len(ok.sent) == 1
    assert session.exec(select(Outbox)).one().sent_at is not None


def test_health_alert_after_three_all_failed_runs(session):
    blocked = {"seek": FakeSource("seek", [], blocked=True)}
    n = FakeNotifier()
    for _ in range(3):
        run_crawl(session, blocked, FakeChain(), n, PROFILE, "https://sh")
    assert sum("SeekHunter: all sources failing" in m for m in n.sent) == 1
    run_crawl(session, blocked, FakeChain(), n, PROFILE, "https://sh")
    assert sum("SeekHunter: all sources failing" in m for m in n.sent) == 1


def test_max_pages_for_caps_non_notify_cities(session):
    from seekhunter.models import SearchProfile

    settings = repo.load_settings(session)
    settings.max_pages_per_search = 5
    settings.other_city_max_pages = 2
    adelaide = SearchProfile(name="a", keywords="dev", location="All Adelaide SA")
    melbourne = SearchProfile(name="m", keywords="dev", location="All Melbourne VIC")
    assert _max_pages_for(adelaide, settings) == 5
    assert _max_pages_for(melbourne, settings) == 2

    settings.other_city_max_pages = 10  # never *raises* the cap above max_pages_per_search
    assert _max_pages_for(melbourne, settings) == 5


def test_crawl_caps_pages_for_non_notify_city_profiles(session):
    melbourne_profile = next(
        p for p in repo.list_search_profiles(session) if p.location == "All Melbourne VIC")
    melbourne_profile.enabled = True
    session.add(melbourne_profile)
    session.commit()

    settings = repo.load_settings(session)
    settings.max_pages_per_search = 5
    settings.other_city_max_pages = 2
    repo.save_settings(session, settings)

    class RecordingSource(FakeSource):
        def __init__(self, name, jobs):
            super().__init__(name, jobs)
            self.max_pages_seen = {}

        def search(self, profile, max_pages):
            self.max_pages_seen[profile.location] = max_pages
            return super().search(profile, max_pages)

    seek = RecordingSource("seek", [jd("seek", "1")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")

    assert seek.max_pages_seen["All Adelaide SA"] == 5
    assert seek.max_pages_seen["All Melbourne VIC"] == 2


def test_crawl_only_notifies_notify_cities_but_still_evaluates_other_cities(session):
    melbourne_profile = next(
        p for p in repo.list_search_profiles(session) if p.location == "All Melbourne VIC")
    melbourne_profile.enabled = True
    session.add(melbourne_profile)
    session.commit()

    class MultiCitySource(FakeSource):
        def search(self, profile, max_pages):
            ext = "mel1" if profile.location == "All Melbourne VIC" else "ade1"
            return [j for j in self.jobs if j.external_id == ext]

    seek = MultiCitySource("seek", [jd("seek", "ade1", title="Adelaide Dev"),
                                    jd("seek", "mel1", title="Melbourne Dev")])
    notifier = FakeNotifier()
    run_crawl(session, {"seek": seek}, FakeChain(), notifier, PROFILE, "https://sh")

    jobs = {j.title: j for j in session.exec(select(Job)).all()}
    adelaide_job, melbourne_job = jobs["Adelaide Dev"], jobs["Melbourne Dev"]
    assert melbourne_job.city == "melbourne"
    # Melbourne is still fully evaluated/scored (not just crawled and dropped)...
    melbourne_eval = session.exec(
        select(JobEvaluation).where(JobEvaluation.job_id == melbourne_job.id)).one()
    assert melbourne_eval.final_score > 0
    # ...but only Adelaide (the default notify_cities) reaches Telegram and gets notified_at set.
    assert adelaide_job.notified_at is not None
    assert melbourne_job.notified_at is None
    assert "Melbourne Dev" not in notifier.sent[0]
    assert "Adelaide Dev" in notifier.sent[0]


def test_recap_respects_notify_cities(session):
    melbourne_profile = next(
        p for p in repo.list_search_profiles(session) if p.location == "All Melbourne VIC")
    melbourne_profile.enabled = True
    session.add(melbourne_profile)
    session.commit()

    class MultiCitySource(FakeSource):
        def search(self, profile, max_pages):
            ext = "mel1" if profile.location == "All Melbourne VIC" else "ade1"
            return [j for j in self.jobs if j.external_id == ext]

    seek = MultiCitySource("seek", [jd("seek", "ade1", title="Adelaide Dev"),
                                    jd("seek", "mel1", title="Melbourne Dev")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")

    n = FakeNotifier()
    run_recap(session, n, "https://sh")
    assert "1 new jobs, 0 excluded" in n.sent[0]
    assert "Melbourne Dev" not in n.sent[0]


def test_recap(session):
    seek = FakeSource("seek", [jd("seek", "1"), jd("seek", "2", company="Westpac")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    n = FakeNotifier()
    run_recap(session, n, "https://sh")
    assert "1 new jobs, 1 excluded" in n.sent[0]


def test_run_insights_brief(session, fixtures_dir):
    from seekhunter.models import utcnow

    now = utcnow()
    for i in range(3):
        data = JobData(source="seek", external_id=f"a{i}", title="Backend Developer", company="Acme",
                       location="adelaide", work_type="contract", url="u", salary_label="$40 - $45 per hour",
                       teaser="Java")
        job, _ = repo.upsert_market_job(session, data, "adelaide", "developer", now, role_family="backend",
                                        skills=["Java"], salary_min_hourly=40.0, salary_max_hourly=45.0)
        repo.apply_market_details(session, job, ["Java"])

    n = FakeNotifier()
    run_insights_brief(session, n, "https://sh", fixtures_dir / "resume")
    assert len(n.sent) == 1
    text = n.sent[0]
    assert text.startswith("SeekHunter weekly market brief")
    assert "Adelaide: 3 jobs" in text
    assert "Java" in text
    assert text.rstrip().endswith("sh/insights")
    assert session.exec(select(Run).where(Run.kind == "insights_brief")).first() is not None


def test_run_insights_brief_dry_run_skips_run_row(session, fixtures_dir):
    n = FakeNotifier()
    run_insights_brief(session, n, "https://sh", fixtures_dir / "resume", dry_run=True)
    assert session.exec(select(Run).where(Run.kind == "insights_brief")).first() is None


def test_run_lock(tmp_path):
    with run_lock(tmp_path):
        with pytest.raises(RunLocked):
            with run_lock(tmp_path):
                pass


def test_recovers_jobs_with_no_evaluation_row(session):
    """A crashed earlier run may have upserted a job without ever evaluating it."""
    data = jd("seek", "1")
    orphan, _ = repo.upsert_job(session, data)
    repo.update_job_details(session, orphan, data)
    assert session.exec(select(JobEvaluation).where(JobEvaluation.job_id == orphan.id)).first() is None

    seek = FakeSource("seek", [])  # nothing new this run
    notifier = FakeNotifier()
    report = run_crawl(session, {"seek": seek}, FakeChain(), notifier, PROFILE, "https://sh")

    assert report.new_jobs == 0
    ev = session.exec(select(JobEvaluation).where(JobEvaluation.job_id == orphan.id)).first()
    assert ev is not None
    session.refresh(orphan)
    assert orphan.notified_at is not None
    assert len(notifier.sent) == 1


def test_details_error_on_one_job_does_not_abort_the_source(session):
    jobs = [jd("seek", "1"), jd("seek", "2", company="Other Co", title="Backend Dev")]
    seek = FlakyDetailsSource("seek", jobs)
    notifier = FakeNotifier()
    report = run_crawl(session, {"seek": seek}, FakeChain(), notifier, PROFILE, "https://sh")

    assert report.new_jobs == 2
    assert report.source_status["seek"]["status"] == "ok"
    assert "details:" in report.source_status["seek"]["error"]
    job2 = session.exec(select(Job).where(Job.external_id == "2")).one()
    assert session.exec(select(JobEvaluation).where(JobEvaluation.job_id == job2.id)).first() is not None


def test_rescore_uses_new_profile_keeps_llm_and_sends_nothing(session):
    seek = FakeSource("seek", [jd("seek", "1", desc="React TypeScript Kotlin")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    ev = session.exec(select(JobEvaluation)).one()
    assert "Kotlin" not in ev.matched_skills

    richer = Profile(skills={"React", "TypeScript", "Kotlin"}, summary="s", titles=[], skill_lines=[],
                     bullets=[])
    assert run_rescore(session, richer) == 1
    session.refresh(ev)
    assert "Kotlin" in ev.matched_skills
    assert ev.llm_score == 50
    assert ev.final_score == round(0.6 * ev.rule_score + 0.4 * 50)


def _hold_lock_for(data_dir, seconds, held_event):  # noqa: ANN001  module-level: picklable for spawn
    import time

    from seekhunter.lock import run_lock

    with run_lock(data_dir):
        held_event.set()
        time.sleep(seconds)


def test_dry_run_does_not_mark_notified_and_real_run_later_notifies(session):
    seek = FakeSource("seek", [jd("seek", "1")])
    dry_notifier = FakeNotifier()
    run_crawl(session, {"seek": seek}, FakeChain(), dry_notifier, PROFILE, "https://sh", dry_run=True)
    assert len(dry_notifier.sent) == 1 and "1 new" in dry_notifier.sent[0]
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    assert job.notified_at is None

    real_notifier = FakeNotifier()
    report = run_crawl(session, {"seek": seek}, FakeChain(), real_notifier, PROFILE, "https://sh")
    assert report.new_jobs == 0
    assert len(real_notifier.sent) == 1 and "1 new" in real_notifier.sent[0]
    session.refresh(job)
    assert job.notified_at is not None


def test_dry_run_leaves_outbox_rows_unsent(session):
    seek = FakeSource("seek", [jd("seek", "1")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(fail=True), PROFILE, "https://sh")
    before = session.exec(select(Outbox)).one()
    assert before.sent_at is None

    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh", dry_run=True)
    after = session.exec(select(Outbox)).one()
    assert after.sent_at is None
    assert after.attempts == before.attempts


def test_rollback_on_source_failure_keeps_other_source_working(session):
    seek = FakeSource("seek", [jd("seek", "1")])
    jora = FakeSource("jora", [jd("jora", "a", title="Vue Developer", company="Other")])
    calls = {"n": 0}
    original_upsert = repo.upsert_job

    def flaky_upsert(session, data, **kwargs):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("SELECT 1", {}, Exception("boom"))
        return original_upsert(session, data, **kwargs)

    import seekhunter.pipeline as pipeline_module

    pipeline_module.repo.upsert_job = flaky_upsert
    try:
        report = run_crawl(session, {"seek": seek, "jora": jora}, FakeChain(), FakeNotifier(), PROFILE,
                           "https://sh")
    finally:
        pipeline_module.repo.upsert_job = original_upsert

    assert report.source_status["seek"]["status"] == "degraded"
    assert report.source_status["jora"]["status"] == "ok"
    jora_job = session.exec(select(Job).where(Job.source == "jora", Job.external_id == "a")).one()
    assert jora_job is not None
    run_row = session.exec(select(Run)).first()
    assert run_row.finished_at is not None


def test_seek_becomes_canonical_over_existing_jora_duplicate(session):
    jora = FakeSource("jora", [jd("jora", "x", title="Data Engineer", company="Foo")])
    first_notifier = FakeNotifier()
    run_crawl(session, {"jora": jora}, FakeChain(), first_notifier, PROFILE, "https://sh")
    jora_job = session.exec(select(Job).where(Job.source == "jora", Job.external_id == "x")).one()
    assert jora_job.notified_at is not None
    assert len(first_notifier.sent) == 1

    seek = FakeSource("seek", [jd("seek", "y", title="Data Engineer", company="Foo")])
    second_notifier = FakeNotifier()
    run_crawl(session, {"seek": seek}, FakeChain(), second_notifier, PROFILE, "https://sh")

    session.refresh(jora_job)
    seek_job = session.exec(select(Job).where(Job.source == "seek", Job.external_id == "y")).one()
    assert jora_job.canonical_job_id == seek_job.id
    assert seek_job.canonical_job_id is None
    assert seek_job.notified_at == jora_job.notified_at
    ev = session.exec(select(JobEvaluation).where(JobEvaluation.job_id == seek_job.id)).first()
    assert ev is not None
    assert seek.detail_calls == 1  # seek is canonical, so its details were fetched
    assert second_notifier.sent == []  # already notified via jora; no duplicate notification


def test_blocking_lock_waits(tmp_path):
    # flock() is scoped per-process (on BSD/macOS) or per-open-file-description (on Linux); either way
    # two threads in the *same* process don't reliably contend with each other. Use a real second
    # process, which also better matches how systemd invokes separate `seekhunter` processes in prod.
    import multiprocessing
    import time

    held = multiprocessing.Event()
    proc = multiprocessing.Process(target=_hold_lock_for, args=(tmp_path, 0.3, held))
    proc.start()
    assert held.wait(timeout=5), "child process never acquired the lock"
    start = time.monotonic()
    with run_lock(tmp_path, blocking=True):
        elapsed = time.monotonic() - start
    proc.join()
    assert elapsed >= 0.15


class ContactLLMChain:
    """Fake LLM that returns a fixed contact_name for every job."""

    def __init__(self, contact_name=None, fit=50):
        self.contact_name, self.fit = contact_name, fit

    def score_batch(self, profile, jobs):
        return {j.key: LLMScore(fit=self.fit, why="ok", contact_name=self.contact_name) for j in jobs}, "fake"


def test_contact_extracted_from_ad_text_on_new_job(session):
    seek = FakeSource("seek", [jd("seek", "1", desc=(
        "React TypeScript role. To apply please call Brayden Mackay on 08 8216 3534 for a "
        "confidential discussion."))])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    assert job.contact_name == "Brayden Mackay"
    assert job.contact_phone == "08 8216 3534"


def test_structured_seek_contact_phone_preferred_over_regex_text():
    """SEEK's structured contactMatches phone/email should win over a different phone found by
    regex in the ad text."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.ensure_seed(s)
        for p in repo.list_search_profiles(s)[1:]:
            p.enabled = False
            s.add(p)
        s.commit()

        class StructuredSource(FakeSource):
            def details(self, job):
                self.detail_calls += 1
                base = next(j for j in self.jobs if j.external_id == job.external_id)
                from dataclasses import replace
                return replace(base, contact_phone="08 8216 3534", contact_email="jobs@acme.com")

        seek = StructuredSource("seek", [jd("seek", "1", desc=(
            "React role. Call Jane Doe on 0412 345 678 for details."))])
        run_crawl(s, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
        job = s.exec(select(Job).where(Job.external_id == "1")).one()
        assert job.contact_phone == "08 8216 3534"
        assert job.contact_email == "jobs@acme.com"
        assert job.contact_name == "Jane Doe"


def test_llm_contact_name_used_when_no_regex_name_and_verbatim_in_text(session):
    seek = FakeSource("seek", [jd("seek", "1", desc="React TypeScript. Our hiring manager is Pat Lee.")])
    run_crawl(session, {"seek": seek}, ContactLLMChain(contact_name="Pat Lee"), FakeNotifier(), PROFILE,
             "https://sh")
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    assert job.contact_name == "Pat Lee"


def test_llm_contact_name_rejected_when_not_verbatim_in_text(session):
    seek = FakeSource("seek", [jd("seek", "1", desc="React TypeScript role, no contact mentioned.")])
    run_crawl(session, {"seek": seek}, ContactLLMChain(contact_name="Made Up Name"), FakeNotifier(), PROFILE,
             "https://sh")
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    assert job.contact_name is None


def test_llm_contact_name_does_not_override_regex_name(session):
    seek = FakeSource("seek", [jd("seek", "1", desc=(
        "React role. Call Brayden Mackay on 08 8216 3534. Pat Lee also helps out."))])
    run_crawl(session, {"seek": seek}, ContactLLMChain(contact_name="Pat Lee"), FakeNotifier(), PROFILE,
             "https://sh")
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    assert job.contact_name == "Brayden Mackay"


def test_contact_lookup_fills_linkedin_for_new_jobs_with_names(session):
    seek = FakeSource("seek", [jd("seek", "1", desc="Call Brayden Mackay on 08 8216 3534.")])
    calls = []

    def fake_lookup(name, company):
        calls.append((name, company))
        return "https://www.linkedin.com/in/brayden-mackay"

    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh",
             contact_lookup=fake_lookup)
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    assert job.contact_linkedin == "https://www.linkedin.com/in/brayden-mackay"
    assert calls == [("Brayden Mackay", "Acme")]


def test_contact_lookup_skipped_without_name(session):
    seek = FakeSource("seek", [jd("seek", "1", desc="No contact mentioned here at all.")])
    calls = []
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh",
             contact_lookup=lambda n, c: calls.append((n, c)) or "https://x")
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    assert job.contact_linkedin is None
    assert calls == []


def test_contact_lookup_failure_is_swallowed(session):
    seek = FakeSource("seek", [jd("seek", "1", desc="Call Brayden Mackay on 08 8216 3534.")])

    def failing_lookup(name, company):
        raise RuntimeError("brave down")

    report = run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh",
                       contact_lookup=failing_lookup)
    assert report.new_jobs == 1
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    assert job.contact_linkedin is None


def test_lookup_linkedin_respects_cap():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        jobs = []
        for i in range(5):
            job, _ = repo.upsert_job(s, jd("seek", str(i)))
            repo.set_contacts(s, job, name=f"Name {i}")
            jobs.append(job)
        calls = []

        def lookup(name, company):
            calls.append(name)
            return f"https://linkedin.com/in/{name}"

        _lookup_linkedin(s, jobs, lookup, cap=2)
        assert len(calls) == 2
        linked = [j for j in jobs if j.contact_linkedin]
        assert len(linked) == 2


def test_run_contacts_backfill_fills_regex_contacts_and_seek_details():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        job, _ = repo.upsert_job(s, jd("seek", "1", desc="Call Brayden Mackay on 08 8216 3534."))

        class BackfillSeekSource:
            def details(self, data):
                from dataclasses import replace
                return replace(data, contact_email="jobs@acme.com")

        report = run_contacts_backfill(s, BackfillSeekSource(), days=7)
        s.refresh(job)
        assert job.contact_name == "Brayden Mackay"
        assert job.contact_phone == "08 8216 3534"
        assert job.contact_email == "jobs@acme.com"
        assert report["jobs_checked"] == 1
        assert report["updated"] == 1


def test_run_contacts_backfill_looks_up_linkedin_when_configured():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        job, _ = repo.upsert_job(s, jd("jora", "1", desc="Call Brayden Mackay on 08 8216 3534."))

        report = run_contacts_backfill(
            s, seek_source=type("S", (), {"details": lambda self, d: d})(),
            contact_lookup=lambda name, company: "https://www.linkedin.com/in/brayden", days=7)
        s.refresh(job)
        assert job.contact_linkedin == "https://www.linkedin.com/in/brayden"
        assert report["linkedin_found"] == 1


def test_run_contacts_backfill_ignores_jobs_outside_window():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        job, _ = repo.upsert_job(s, jd("seek", "1", desc="Call Brayden Mackay on 08 8216 3534."))
        job.first_seen_at = job.first_seen_at.replace(year=job.first_seen_at.year - 1)
        s.add(job)
        s.commit()

        report = run_contacts_backfill(s, seek_source=type("S", (), {"details": lambda self, d: d})(),
                                       days=7)
        assert report["jobs_checked"] == 0


def test_new_seek_job_persists_insights_from_details(session):
    seek = FakeSource("seek", [jd("seek", "1", applicant_count=77,
                                  applicant_volume="Medium application volume", resume_pct=100,
                                  cover_letter_pct=57)])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    assert job.applicant_count == 77
    assert job.applicant_volume == "Medium application volume"
    assert job.resume_pct == 100
    assert job.cover_letter_pct == 57
    assert job.insights_checked_at is not None


def test_jora_job_details_do_not_touch_insights(session):
    jora = FakeSource("jora", [jd("jora", "a")])
    run_crawl(session, {"jora": jora}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    job = session.exec(select(Job).where(Job.external_id == "a")).one()
    assert job.applicant_count is None
    assert job.insights_checked_at is None


def test_run_crawl_refreshes_insights_for_jobs_never_checked(session):
    seek = FakeSource("seek", [jd("seek", "1")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    job.insights_checked_at = None  # simulate a row migrated in before this feature existed
    session.add(job)
    session.commit()

    seek.jobs = [jd("seek", "1", applicant_count=12, applicant_volume="Low application volume")]
    report = run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    session.refresh(job)
    assert job.applicant_count == 12
    assert job.applicant_volume == "Low application volume"
    assert job.insights_checked_at is not None
    assert report.source_status["seek"]["insights_refreshed"] == 1


def test_run_crawl_skips_insights_refresh_checked_within_three_hours(session):
    seek = FakeSource("seek", [jd("seek", "1")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    report = run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    assert report.source_status["seek"]["insights_refreshed"] == 0


def test_run_crawl_insights_source_blocked_stops_loop_and_is_recorded(session):
    seek = FakeSource("seek", [jd("seek", "1"), jd("seek", "2", company="Other", title="Backend Dev")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    # Both jobs already got an insights check at creation time; force them to look overdue again
    # so the next run's refresh loop actually has jobs to process.
    for job in session.exec(select(Job).where(Job.source == "seek")).all():
        job.insights_checked_at = None
        session.add(job)
    session.commit()

    seek.insights_blocked = True
    report = run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    assert report.source_status["seek"]["insights_error"] == "403"
    assert report.source_status["seek"]["insights_refreshed"] == 0


def test_run_crawl_insights_refresh_without_seek_source_is_a_noop(session):
    jora = FakeSource("jora", [jd("jora", "a")])
    report = run_crawl(session, {"jora": jora}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    assert "seek" not in report.source_status


def test_run_crawl_runs_insights_refresh_during_dry_run_too(session):
    seek = FakeSource("seek", [jd("seek", "1")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    job.insights_checked_at = None
    session.add(job)
    session.commit()

    report = run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh",
                       dry_run=True)
    assert report.source_status["seek"]["insights_refreshed"] == 1


def test_run_insights_refresh_reports_checked_and_refreshed_counts():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        job, _ = repo.upsert_job(s, jd("seek", "1", applicant_count=9))
        seek = FakeSource("seek", [jd("seek", "1", applicant_count=9)])
        report = run_insights_refresh(s, seek, limit=10)
        s.refresh(job)
        assert report == {"checked": 1, "refreshed": 1, "error": None}
        assert job.applicant_count == 9


def test_run_insights_refresh_generic_exception_is_skipped_and_continues():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.upsert_job(s, jd("seek", "1"))
        repo.upsert_job(s, jd("seek", "2"))

        class FlakyInsightsSource(FakeSource):
            def insights(self, external_id):
                self.insights_calls += 1
                if external_id == "1":
                    raise ValueError("boom")
                return {"applicant_count": 3}

        seek = FlakyInsightsSource("seek", [jd("seek", "1"), jd("seek", "2")])
        report = run_insights_refresh(s, seek, limit=10)
        assert report == {"checked": 2, "refreshed": 1, "error": None}


def test_run_crawl_upserts_named_recruiter_into_contacts(session):
    seek = FakeSource("seek", [jd("seek", "1", desc="Call Brayden Mackay on 08 8216 3534.")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    job = session.exec(select(Job).where(Job.external_id == "1")).one()
    contact = session.exec(select(Contact).where(Contact.name == "Brayden Mackay")).one()
    assert contact.company == "Acme" and contact.phone == "08 8216 3534"
    link = session.exec(select(ContactJob).where(ContactJob.contact_id == contact.id)).one()
    assert link.job_id == job.id


def test_run_crawl_skips_contact_upsert_without_a_name(session):
    seek = FakeSource("seek", [jd("seek", "1", desc="No contact mentioned here at all.")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    assert session.exec(select(Contact)).first() is None


def test_run_contacts_backfill_upserts_named_recruiter_into_contacts():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        job, _ = repo.upsert_job(s, jd("seek", "1", desc="Call Brayden Mackay on 08 8216 3534."))

        class BackfillSeekSource:
            def details(self, data):
                from dataclasses import replace
                return replace(data, contact_email="jobs@acme.com")

        run_contacts_backfill(s, BackfillSeekSource(), days=7)
        contact = s.exec(select(Contact).where(Contact.name == "Brayden Mackay")).one()
        assert contact.email == "jobs@acme.com"
        link = s.exec(select(ContactJob).where(ContactJob.contact_id == contact.id)).one()
        assert link.job_id == job.id


def test_digest_item_includes_already_applied_when_prior_application_exists(session):
    job, _ = repo.upsert_job(session, jd("seek", "1"))
    ev = repo.save_evaluation(session, job.id, excluded=False, reasons=[], snippets={}, rule_score=70,
                              llm_score=None, llm_note=None, llm_provider=None, final_score=70,
                              matched_skills=[], flags=[])
    now = _utcnow()
    prior = repo.create_application(session, job_id=None, company="Acme", title="Old Role",
                                    applied_at=now - timedelta(days=3))
    item = digest_item(job, ev, prior, now)
    assert item.already_applied_title == "Old Role"
    assert item.already_applied_days_ago == 3


def test_digest_item_omits_already_applied_without_prior_application(session):
    job, _ = repo.upsert_job(session, jd("seek", "1"))
    ev = repo.save_evaluation(session, job.id, excluded=False, reasons=[], snippets={}, rule_score=70,
                              llm_score=None, llm_note=None, llm_provider=None, final_score=70,
                              matched_skills=[], flags=[])
    item = digest_item(job, ev)
    assert item.already_applied_title is None
    assert item.already_applied_days_ago is None


def test_run_crawl_digest_mentions_already_applied_company(session):
    repo.create_application(session, job_id=None, company="Acme", title="Old Role",
                            applied_at=_utcnow() - timedelta(days=3))
    seek = FakeSource("seek", [jd("seek", "1", company="Acme")])
    notifier = FakeNotifier()
    run_crawl(session, {"seek": seek}, FakeChain(), notifier, PROFILE, "https://sh")
    assert any("Already applied: Old Role (3d ago)" in m for m in notifier.sent)


def test_run_recap_includes_follow_up_line_for_stale_applications(session):
    repo.create_application(session, job_id=None, company="Acme", title="Stale Role",
                            applied_at=_utcnow() - timedelta(days=9))
    seek = FakeSource("seek", [jd("seek", "1")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    n = FakeNotifier()
    run_recap(session, n, "https://sh")
    assert any("Follow up: Acme · Stale Role · 9d" in m for m in n.sent)


def test_run_recap_omits_follow_up_line_when_nothing_due(session):
    seek = FakeSource("seek", [jd("seek", "1")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    n = FakeNotifier()
    run_recap(session, n, "https://sh")
    assert not any("Follow up:" in m for m in n.sent)
