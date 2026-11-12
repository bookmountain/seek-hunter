from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import repo
from seekhunter.domain import JobData
from seekhunter.funnel import Row, funnel
from seekhunter.models import utcnow


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.ensure_seed(s)
        yield s


def _app(session, *, source="seek", company="Acme", work_type="contract", ext=None, days=10, manual=False):
    applied_at = utcnow() - timedelta(days=days)
    if manual:
        app = repo.create_application(session, job_id=None, company=company, title="Dev",
                                      applied_at=applied_at, source="manual")
        return app, None
    job, _ = repo.upsert_job(session, JobData(source=source, external_id=ext or f"{source}-{company}-{days}",
                                              title="Dev", company=company, location="Adelaide SA",
                                              work_type=work_type, url="u"))
    return repo.ensure_application_for_job(session, job, applied_at), job


def _row(rows, label):
    return next(r for r in rows if r["label"] == label)


def test_row_rates_and_empty_rates():
    r = Row(label="x", applied=4, responded=1, interview=1)
    assert r.response_rate == 0.25 and r.interview_rate == 0.25
    assert Row(label="y").response_rate is None


def test_empty_funnel(session):
    out = funnel(session)
    assert out["total"] == {"label": "all", "applied": 0, "responded": 0, "interview": 0, "offer": 0,
                            "response_rate": None, "interview_rate": None}
    assert out["by_source"] == []


def test_stage_history_counts_even_after_rejection(session):
    a, _ = _app(session, company="A")
    repo.update_application(session, a, stage="interview")
    repo.update_application(session, a, stage="rejected")
    b, _ = _app(session, company="B")
    repo.update_application(session, b, stage="rejected")  # a "no" is still a response
    c, _ = _app(session, company="C")
    repo.update_application(session, c, stage="offer")
    _app(session, company="D")  # no answer
    total = funnel(session)["total"]
    assert (total["applied"], total["responded"], total["interview"], total["offer"]) == (4, 3, 2, 1)
    assert total["response_rate"] == 0.75 and total["interview_rate"] == 0.5


def test_logged_reply_counts_as_responded(session):
    a, job = _app(session, company="Hays Recruitment")
    c = repo.upsert_contact(session, name="Brayden Mackay", company="Hays Recruitment")
    repo.link_contact_job(session, c.id, job.id)
    repo.create_interaction(session, contact_id=c.id, kind="linkedin_reply")
    total = funnel(session)["total"]
    assert total["responded"] == 1 and total["interview"] == 0


def test_breakdowns_by_source_employer_and_work_type(session):
    a, _ = _app(session, source="seek", company="Hays Recruitment", work_type="contract")
    repo.update_application(session, a, stage="screening")
    _app(session, source="linkedin", company="Atlassian", work_type="full_time")
    _app(session, manual=True, company="Canva")
    out = funnel(session)
    assert [r["label"] for r in out["by_source"]] == ["seek", "linkedin", "manual"]
    assert _row(out["by_source"], "seek")["responded"] == 1
    assert _row(out["by_employer"], "agency") == {
        "label": "agency", "applied": 1, "responded": 1, "interview": 0, "offer": 0,
        "response_rate": 1.0, "interview_rate": 0.0}
    assert _row(out["by_employer"], "direct")["applied"] == 2
    assert [r["label"] for r in out["by_work_type"]] == ["contract", "full_time", "unknown"]


def test_radar_source_is_its_own_bucket(session):
    _app(session, source="radar", company="Maptek")
    assert [r["label"] for r in funnel(session)["by_source"]] == ["radar"]


def test_called_before_or_at_applying(session):
    a, job_a = _app(session, company="A", days=10)
    ca = repo.upsert_contact(session, name="Jane Citizen", company="A")
    repo.link_contact_job(session, ca.id, job_a.id)
    repo.create_interaction(session, contact_id=ca.id, kind="call", at=a.applied_at - timedelta(hours=2))
    repo.update_application(session, a, stage="interview")

    b, job_b = _app(session, company="B", days=10)
    cb = repo.upsert_contact(session, name="Jo Smith", company="B")
    repo.link_contact_job(session, cb.id, job_b.id)
    repo.create_interaction(session, contact_id=cb.id, kind="voicemail", at=b.applied_at)

    c, job_c = _app(session, company="C", days=10)
    cc = repo.upsert_contact(session, name="Sam Lee", company="C")
    repo.link_contact_job(session, cc.id, job_c.id)
    later = c.applied_at + timedelta(days=3)
    repo.create_interaction(session, contact_id=cc.id, kind="call", at=later)

    rows = funnel(session)["by_call"]
    assert [(r["label"], r["applied"], r["interview"]) for r in rows] == [
        ("called", 1, 1), ("voicemail", 1, 0), ("not called", 1, 0)]


def test_days_window(session):
    _app(session, company="Old", days=100)
    _app(session, company="New", days=3)
    from seekhunter.models import utcnow as now
    assert funnel(session, since=now() - timedelta(days=30))["total"]["applied"] == 1
