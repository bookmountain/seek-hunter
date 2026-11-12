from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from seekhunter import repo
from seekhunter.llm.base import LLMScore
from seekhunter.models import Job, utcnow
from seekhunter.notify import DigestItem, format_instant_alert
from seekhunter.pipeline import instant_alert_candidates, run_crawl, send_instant_alerts
from tests.test_pipeline import PROFILE, FakeNotifier, FakeSource, jd


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


class HighChain:
    def score_batch(self, profile, jobs):
        return {j.key: LLMScore(fit=100, why="great") for j in jobs}, "fake"


def _job(session, ext, score=80, city="adelaide", applicants=None, listed_hours_ago=1, source="radar",
         excluded=False):
    job, _ = repo.upsert_job(session, jd(source, ext, title=f"Dev {ext}", company=f"Co {ext}"))
    job.city = city
    job.applicant_count = applicants
    job.listed_at = utcnow() - timedelta(hours=listed_hours_ago) if listed_hours_ago is not None else None
    session.add(job)
    session.commit()
    repo.save_evaluation(session, job.id, excluded=excluded, reasons=[], snippets={}, rule_score=score,
                         final_score=score, matched_skills=["React"], flags=[])
    return job


def _settings(session):
    s = repo.load_settings(session)
    s.instant_alert_min_score, s.instant_alert_max_applicants = 70, 20
    return s


def test_candidates_apply_score_applicants_city_and_age_rules(session):
    ok = _job(session, "ok")
    unknown_applicants = _job(session, "unknown", applicants=None, listed_hours_ago=None)
    at_limit = _job(session, "limit", applicants=20, score=70)
    low = _job(session, "low", score=69)
    crowded = _job(session, "crowded", applicants=21)
    melbourne = _job(session, "melb", city="melbourne")
    old = _job(session, "old", listed_hours_ago=30)
    excluded = _job(session, "excl", excluded=True)
    jobs = [ok, unknown_applicants, at_limit, low, crowded, melbourne, old, excluded]
    got = {j.external_id for j, _ in instant_alert_candidates(session, jobs, _settings(session), utcnow())}
    assert got == {"ok", "unknown", "limit"}


def test_candidates_skip_duplicates_and_already_notified(session):
    canonical = _job(session, "c")
    dup = _job(session, "d")
    dup.canonical_job_id = canonical.id
    canonical.notified_at = utcnow()
    session.add_all([dup, canonical])
    session.commit()
    assert instant_alert_candidates(session, [canonical, dup], _settings(session), utcnow()) == []


def test_send_marks_notified_and_formats_message(session):
    job = _job(session, "x", applicants=4)
    job.contact_phone = "0412 345 678"
    session.add(job)
    session.commit()
    notifier = FakeNotifier()
    ids = send_instant_alerts(session, [job], _settings(session), notifier, "seekhunter.example", utcnow())
    assert ids == [job.id]
    assert len(notifier.sent) == 1
    lines = notifier.sent[0].splitlines()
    assert lines[0] == f"Just posted · #{job.id} · 80 · Dev x — Co x · Contract · radar"
    assert lines[1] == "4 applicants · 0412 345 678"
    assert lines[2] == f"https://seekhunter.example/?job={job.id}"
    assert lines[3] == f"Reply to OpenClaw: tailor {job.id}"
    session.refresh(job)
    assert job.notified_at is not None
    # a second pass doesn't resend
    assert send_instant_alerts(session, [job], _settings(session), notifier, "x", utcnow()) == []


def test_send_does_nothing_when_notifications_are_off_and_dry_run_marks_nothing(session):
    job = _job(session, "x")
    settings = _settings(session)
    settings.notify_enabled = False
    notifier = FakeNotifier()
    assert send_instant_alerts(session, [job], settings, notifier, "x", utcnow()) == []
    assert notifier.sent == []
    settings.notify_enabled = True
    assert send_instant_alerts(session, [job], settings, notifier, "x", utcnow(), dry_run=True) == [job.id]
    session.refresh(job)
    assert job.notified_at is None


def test_format_unknown_applicants_without_phone():
    it = DigestItem(job_id=3, score=75, title="T", company="C", location="Adelaide SA", work_type="part_time",
                    matched=[], why=None, url="u")
    text = format_instant_alert(it, "indeed", "https://h/")
    assert text.splitlines()[1] == "applicants unknown"
    assert "Part time · indeed" in text.splitlines()[0]


def test_crawl_sends_instant_alert_and_leaves_it_out_of_the_digest(session):
    seek = FakeSource("seek", [
        jd("seek", "1", title="React Developer", desc="React TypeScript part-time role"),
        jd("seek", "2", title="Vue Developer", company="Other", desc="Vue", wt="full_time"),
    ])
    settings = repo.load_settings(session)
    settings.instant_alert_min_score = 60
    repo.save_settings(session, settings)
    notifier = FakeNotifier()
    report = run_crawl(session, {"seek": seek}, HighChain(), notifier, PROFILE, "https://sh")
    jobs = {j.external_id: j for j in session.exec(select(Job)).all()}
    alerts = [m for m in notifier.sent if m.startswith("Just posted")]
    assert len(alerts) == 1 and f"#{jobs['1'].id}" in alerts[0]
    digests = [m for m in notifier.sent if m.startswith("SeekHunter —")]
    assert digests and f"#{jobs['1'].id} " not in digests[0]
    assert f"#{jobs['2'].id} " in digests[0]
    assert jobs["1"].notified_at is not None
    assert report.notified == 2
