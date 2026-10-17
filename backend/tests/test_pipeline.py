import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

from seekhunter import repo
from seekhunter.domain import JobData
from seekhunter.http import SourceBlocked
from seekhunter.llm.base import LLMScore
from seekhunter.lock import RunLocked, run_lock
from seekhunter.models import Job, JobEvaluation, Outbox, Run
from seekhunter.notify import NotifyError
from seekhunter.pipeline import run_crawl, run_recap, run_rescore
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


def jd(source, ext, title="React Developer", company="Acme", desc="React TypeScript", wt="contract"):
    return JobData(source=source, external_id=ext, title=title, company=company, location="Adelaide SA",
                   work_type=wt, url=f"https://x/{source}/{ext}", description_html=f"<p>{desc}</p>")


class FakeSource:
    def __init__(self, name, jobs, blocked=False):
        self.name, self.jobs, self.blocked = name, jobs, blocked
        self.client = type("C", (), {"request_count": 0, "blocked_count": 0})()
        self.detail_calls = 0

    def search(self, profile, max_pages):
        if self.blocked:
            raise SourceBlocked("403")
        return [JobData(**{**j.__dict__, "description_html": ""}) for j in self.jobs]

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


def test_recap(session):
    seek = FakeSource("seek", [jd("seek", "1"), jd("seek", "2", company="Westpac")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    n = FakeNotifier()
    run_recap(session, n, "https://sh")
    assert "1 new jobs, 1 excluded" in n.sent[0]


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

    def flaky_upsert(session, data):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("SELECT 1", {}, Exception("boom"))
        return original_upsert(session, data)

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
