"""Closed-listing detection: per-board parsers, the re-check pass, and list visibility."""

from datetime import timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import repo
from seekhunter.domain import JobData
from seekhunter.http import SourceBlocked
from seekhunter.models import utcnow
from seekhunter.pipeline import check_closed
from seekhunter.sources import jora, linkedin
from seekhunter.sources.seek import SeekSource

JORA_CLOSED = ('<main><div class="flash-container error"><div class="messages"><div>This job is no '
               'longer available at Akkodis Australia</div></div></div>'
               '<div id="job-description-container">x</div></main>')
JORA_OPEN = '<main><div id="job-description-container"><p>Java</p></div></main>'


def test_jora_closed_banner():
    assert jora.parse_closed(JORA_CLOSED) is True
    assert jora.parse_closed(JORA_OPEN) is False
    assert jora.parse_closed("<html><body>captcha</body></html>") is None


def test_linkedin_closed_text():
    assert linkedin.parse_closed("<body><span>No longer accepting applications</span></body>") is True
    assert linkedin.parse_closed('<body><div class="show-more-less-html__markup">Hi</div></body>') is False
    assert linkedin.parse_closed("<body></body>") is None


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _Client:
    def __init__(self, payload):
        self.payload = payload

    def post(self, url, **kw):
        return _Resp(self.payload)


@pytest.mark.parametrize("payload,expected", [
    ({"data": {"jobDetails": {"job": {"id": "1", "isExpired": True}}}}, True),
    ({"data": {"jobDetails": {"job": {"id": "1", "isExpired": False}}}}, False),
    ({"data": {"jobDetails": None}}, True),
    ({"errors": [{"message": "boom"}]}, None),
])
def test_seek_is_expired(payload, expected):
    job = JobData(source="seek", external_id="1", title="t", company="c", location="", work_type="contract",
                  url="u")
    assert SeekSource(_Client(payload)).is_closed(job) is expected


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _job(session, ext, status="new", age_hours=48, source="jora"):
    job, _ = repo.upsert_job(session, JobData(source=source, external_id=ext, title=f"Dev {ext}",
                                              company=f"Co {ext}", location="Adelaide SA",
                                              work_type="contract", url=ext))
    job.first_seen_at = utcnow() - timedelta(hours=age_hours)
    job.status = status
    session.add(job)
    session.commit()
    repo.save_evaluation(session, job.id, excluded=False, reasons=[], snippets={}, rule_score=70,
                         final_score=70, matched_skills=[], flags=[])
    return job


class _Board:
    def __init__(self, closed: set[str], blocked=False):
        self.closed, self.blocked, self.calls = closed, blocked, []

    def is_closed(self, job):
        self.calls.append(job.external_id)
        if self.blocked:
            raise SourceBlocked("blocked")
        return job.external_id in self.closed


def test_check_closed_hides_closed_ads_but_keeps_saved_and_applied(session):
    for ext, status in (("a", "new"), ("b", "new"), ("c", "saved"), ("d", "applied")):
        _job(session, ext, status)
    fresh = _job(session, "fresh", age_hours=2)
    board = _Board({"a", "c", "d"})
    counts = check_closed(session, {"jora": board}, limit=10)
    assert counts == {"jora": {"checked": 4, "closed": 3}}
    assert "fresh" not in board.calls and fresh.closed_at is None  # under 12h old: not checked
    listed = {j.external_id for j, _ in repo.list_jobs(session)}
    assert listed == {"b", "c", "d", "fresh"}  # closed "a" gone; saved/applied kept
    assert {j.external_id for j, _ in repo.list_jobs(session, status="closed")} == {"a", "c", "d"}
    assert all(j.closed_at is None for j, _ in repo.notification_candidates(session, utcnow()))


def test_check_closed_prefers_ads_missing_from_search_and_stops_on_block(session):
    seen, unseen = _job(session, "seen"), _job(session, "unseen")
    seen.last_seen_at = utcnow()
    unseen.last_seen_at = utcnow() - timedelta(days=3)
    session.add_all([seen, unseen])
    session.commit()
    board = _Board(set())
    check_closed(session, {"jora": board}, limit=1)
    assert board.calls == ["unseen"]
    blocked = _Board(set(), blocked=True)
    assert check_closed(session, {"jora": blocked}, limit=5) == {"jora": {"checked": 0, "closed": 0}}
    assert len(blocked.calls) == 1  # one block stops that source for the pass


def test_excluded_jobs_are_not_rechecked(session):
    job = _job(session, "ex")
    repo.save_evaluation(session, job.id, excluded=True, reasons=["clearance"], snippets={}, rule_score=0,
                         final_score=0, matched_skills=[], flags=[])
    board = _Board(set())
    check_closed(session, {"jora": board}, limit=5)
    assert board.calls == []


def test_search_hit_bumps_last_seen(session):
    job = _job(session, "x")
    job.last_seen_at = None
    session.add(job)
    session.commit()
    again, is_new = repo.upsert_job(session, JobData(source="jora", external_id="x", title="Dev x",
                                                     company="Co x", location="Adelaide SA",
                                                     work_type="contract", url="x"))
    assert not is_new and again.last_seen_at is not None
