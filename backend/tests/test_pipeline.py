import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from seekhunter import repo
from seekhunter.domain import JobData
from seekhunter.http import SourceBlocked
from seekhunter.llm.base import LLMScore
from seekhunter.lock import RunLocked, run_lock
from seekhunter.models import Job, JobEvaluation, Outbox
from seekhunter.notify import NotifyError
from seekhunter.pipeline import run_crawl, run_recap
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
    assert len(notifier.sent) == 1 and "2 new" in notifier.sent[0]

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
    assert "jora unavailable" in notifier.sent[0]


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
    assert sum("⚠️ SeekHunter" in m for m in n.sent) == 1
    run_crawl(session, blocked, FakeChain(), n, PROFILE, "https://sh")
    assert sum("⚠️ SeekHunter" in m for m in n.sent) == 1


def test_recap(session):
    seek = FakeSource("seek", [jd("seek", "1"), jd("seek", "2", company="Westpac")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    n = FakeNotifier()
    run_recap(session, n, "https://sh")
    assert "1 new jobs · 1 excluded" in n.sent[0]


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
