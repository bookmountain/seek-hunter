import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import call_script, repo
from seekhunter.api import create_app
from seekhunter.config import get_env
from seekhunter.db import get_session
from seekhunter.domain import JobData
from seekhunter.models import utcnow

AUTH = {"Authorization": "Bearer t0k"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_WRITE_TOKEN", "t0k")
    monkeypatch.setenv("ALLOWED_CIDRS", "127.0.0.1/32,testclient/32")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    monkeypatch.setenv("RESUME_DIR", str(Path(__file__).parent / "fixtures" / "resume"))
    (tmp_path / "index.html").write_text("<html>spa</html>")
    get_env.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.ensure_seed(s)
        job, _ = repo.upsert_job(s, JobData(
            source="seek", external_id="1", title="React Developer", company="Hays Recruitment",
            location="Adelaide SA", work_type="contract", url="u",
            description_html="<p>React, TypeScript</p>"))
        repo.set_contacts(s, job, name="Brayden Mackay", phone="08 8216 3534")
        repo.save_evaluation(s, job.id, excluded=False, reasons=[], snippets={}, rule_score=70,
                             llm_score=None, llm_note=None, llm_provider=None, final_score=70,
                             matched_skills=["React"], flags=[])

    def override():
        with Session(engine) as s:
            yield s

    app = create_app(init=False)
    app.dependency_overrides[get_session] = override
    c = TestClient(app)
    yield c
    get_env.cache_clear()


def _job_id(client):
    return client.get("/api/jobs").json()[0]["id"]


def _llm(monkeypatch, replies):
    calls = []

    def fake(prompt):
        calls.append(prompt)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(call_script, "text_llms", lambda settings, env: [("openclaw", fake)])
    return calls


GOOD = json.dumps({"questions": ["A?", "B?", "C?"],
                   "pitch": "I'm a Software Engineer with 5 years of experience, working with React."})


# --------------------------------------------------------------------------------------- call script


def test_get_call_script_is_an_uncached_template_preview(client, monkeypatch):
    calls = _llm(monkeypatch, [])
    r = client.get(f"/api/jobs/{_job_id(client)}/call-script")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "template" and body["cached"] is False and body["agency"] is True
    assert len(body["questions"]) == 3
    assert body["pitch"].startswith("Hi Brayden, it's Book Sam.")
    assert calls == []  # GET never calls the LLM


def test_post_generates_caches_and_reuses(client, monkeypatch):
    calls = _llm(monkeypatch, [GOOD, GOOD])
    jid = _job_id(client)
    assert client.post(f"/api/jobs/{jid}/call-script").status_code == 401
    r = client.post(f"/api/jobs/{jid}/call-script", headers=AUTH).json()
    assert r["source"] == "llm" and r["provider"] == "openclaw" and r["cached"] is True
    assert r["questions"] == ["A?", "B?", "C?"]
    assert r["pitch"].endswith(call_script.AVAILABILITY_FLEXIBLE)
    assert "<<<JOB_AD" in calls[0]
    # cached: GET and a second POST don't call the model again
    assert client.get(f"/api/jobs/{jid}/call-script").json()["questions"] == ["A?", "B?", "C?"]
    client.post(f"/api/jobs/{jid}/call-script", headers=AUTH)
    assert len(calls) == 1
    client.post(f"/api/jobs/{jid}/call-script?refresh=1", headers=AUTH)
    assert len(calls) == 2


def test_post_falls_back_to_template_when_llm_down(client, monkeypatch):
    from seekhunter.llm.base import LLMUnavailable

    _llm(monkeypatch, [LLMUnavailable("down"), GOOD])
    jid = _job_id(client)
    r = client.post(f"/api/jobs/{jid}/call-script", headers=AUTH).json()
    assert r["source"] == "template" and r["warnings"] == ["AI unavailable; this is the template script."]
    # a cached template is retried on the next POST (the LLM may be back)
    assert client.post(f"/api/jobs/{jid}/call-script", headers=AUTH).json()["source"] == "llm"


def test_call_script_404(client):
    assert client.get("/api/jobs/999/call-script").status_code == 404


def test_contact_log_accepts_voicemail_with_note(client):
    jid = _job_id(client)
    r = client.post(f"/api/jobs/{jid}/contact-log", json={"kind": "voicemail", "note": "left msg 9am"},
                    headers=AUTH)
    assert r.status_code == 201
    assert r.json()["kind"] == "voicemail" and r.json()["note"] == "left msg 9am"


def test_interactions_accept_linkedin_reply_and_contacts_show_status(client):
    cid = client.post("/api/contacts", json={"name": "Sam Lee", "company": "Acme"}, headers=AUTH).json()["id"]
    for kind in ("linkedin_invite", "linkedin_accepted", "linkedin_reply"):
        assert client.post("/api/interactions", json={"contact_id": cid, "kind": kind},
                           headers=AUTH).status_code == 201
    (contact,) = client.get("/api/contacts").json()
    assert contact["linkedin_status"] == "replied"


# ------------------------------------------------------------------------------------------ follow-ups


def _stale_app(client, days=6, company="Globex"):
    applied_at = (utcnow() - timedelta(days=days)).isoformat()
    return client.post("/api/applications", headers=AUTH,
                       json={"company": company, "title": "Dev", "applied_at": applied_at}).json()["id"]


def test_follow_ups_list_and_actions(client):
    app_id = _stale_app(client)
    _stale_app(client, company="Initech")
    items = client.get("/api/follow-ups").json()
    assert [i["application_id"] for i in items][:1] == [app_id]
    key = items[0]["key"]
    assert items[0]["kind"] == "application_nudge" and items[0]["message"].startswith("Hi there,")

    assert client.post(f"/api/follow-ups/{key}/snooze", json={"days": 2}).status_code == 401
    assert client.post(f"/api/follow-ups/{key}/snooze", json={"days": 2}, headers=AUTH).status_code == 204
    assert len(client.get("/api/follow-ups").json()) == 1
    other = client.get("/api/follow-ups").json()[0]["key"]
    assert client.post(f"/api/follow-ups/{other}/dismiss", headers=AUTH).status_code == 204
    assert client.get("/api/follow-ups").json() == []
    assert client.post("/api/follow-ups/nope-1-2/dismiss", headers=AUTH).status_code == 404


def test_follow_up_done_logs_interaction(client):
    app_id = _stale_app(client)
    key = client.get("/api/follow-ups").json()[0]["key"]
    r = client.post(f"/api/follow-ups/{key}/done", json={"note": "emailed HR"}, headers=AUTH)
    assert r.status_code == 204
    assert client.get("/api/follow-ups").json() == []
    timeline = client.get("/api/history").json()
    assert any(e["kind"] == "email" and e["application_id"] == app_id and e["note"] == "emailed HR"
               for e in timeline)


def test_snooze_days_validated(client):
    _stale_app(client)
    key = client.get("/api/follow-ups").json()[0]["key"]
    assert client.post(f"/api/follow-ups/{key}/snooze", json={"days": 0}, headers=AUTH).status_code == 422


def test_follow_ups_summary_text(client):
    _stale_app(client)
    r = client.get("/api/follow-ups/summary")
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text.startswith("Follow-ups due: 1")
    assert "1. Nudge · Globex · Dev · applied, quiet 6d" in r.text


def test_bell_lists_linkedin_follow_ups(client):
    cid = client.post("/api/contacts", json={"name": "Sam Lee", "company": "Acme"}, headers=AUTH).json()["id"]
    client.post("/api/interactions", json={"contact_id": cid, "kind": "linkedin_accepted"}, headers=AUTH)
    items = [i for i in client.get("/api/notifications").json()["items"] if i["type"] == "follow_up"]
    assert [(i["title"], i["subtitle"]) for i in items] == [("Sam Lee", "Say thanks · Sam Lee · Acme")]


# ---------------------------------------------------------------------------------------------- funnel


def test_funnel_endpoint(client):
    jid = _job_id(client)
    app = client.patch(f"/api/jobs/{jid}", json={"status": "applied"}, headers=AUTH).json()["application"]
    client.post(f"/api/jobs/{jid}/contact-log", json={"kind": "call"}, headers=AUTH)
    client.patch(f"/api/applications/{app['id']}", json={"stage": "interview"}, headers=AUTH)
    _stale_app(client)
    out = client.get("/api/funnel").json()
    assert out["total"]["applied"] == 2 and out["total"]["interview"] == 1
    assert out["total"]["response_rate"] == 0.5
    assert [(r["label"], r["applied"]) for r in out["by_source"]] == [("seek", 1), ("manual", 1)]
    assert [(r["label"], r["interview"]) for r in out["by_call"]] == [("called", 1), ("not called", 0)]
    assert [r["label"] for r in out["by_employer"]] == ["agency", "direct"]
    assert client.get("/api/funnel?days=0").status_code == 422
    assert client.get("/api/funnel?days=1").json()["total"]["applied"] == 1
