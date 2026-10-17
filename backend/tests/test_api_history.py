from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import repo
from seekhunter.api import create_app
from seekhunter.config import get_env
from seekhunter.db import get_session
from seekhunter.domain import JobData, company_key
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
        job, _ = repo.upsert_job(s, JobData(source="seek", external_id="1", title="React Dev", company="Acme",
                                            location="Adelaide SA", work_type="contract", url="u",
                                            description_html="<p>React</p>"))
        repo.save_evaluation(s, job.id, excluded=False, reasons=[], snippets={}, rule_score=70,
                             llm_score=None, llm_note=None, llm_provider=None, final_score=70,
                             matched_skills=["React"], flags=[])

    def override():
        with Session(engine) as s:
            yield s

    app = create_app(init=False)
    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    get_env.cache_clear()


def _job_id(client):
    return client.get("/api/jobs").json()[0]["id"]


# ---------------------------------------------------------------------------- applied auto-creates app


def test_patch_applied_auto_creates_application_idempotently(client):
    job_id = _job_id(client)
    r = client.patch(f"/api/jobs/{job_id}", json={"status": "applied"}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "applied"
    assert body["application"]["stage"] == "applied"
    app_id = body["application"]["id"]

    apps = client.get("/api/applications").json()
    assert len(apps) == 1
    assert apps[0]["job_id"] == job_id
    assert apps[0]["company"] == "Acme"

    # idempotent: patching to applied again does not create a second application
    r2 = client.patch(f"/api/jobs/{job_id}", json={"status": "applied"}, headers=AUTH)
    assert r2.json()["application"]["id"] == app_id
    assert len(client.get("/api/applications").json()) == 1


def test_patch_applied_attaches_latest_done_tailoring(client, monkeypatch):
    job_id = _job_id(client)

    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: calls.append((a, k)))
    r = client.post(f"/api/jobs/{job_id}/tailor", headers=AUTH)
    tid = r.json()["tailoring_id"]

    # Mark the tailoring done directly through the overridden session dependency.
    override = client.app.dependency_overrides[get_session]
    with next(override()) as s:
        from seekhunter.models import Tailoring

        t = s.get(Tailoring, tid)
        t.status = "done"
        s.add(t)
        s.commit()

    r2 = client.patch(f"/api/jobs/{job_id}", json={"status": "applied"}, headers=AUTH)
    assert r2.json()["application"]["tailoring_id"] == tid


def test_patch_applied_upserts_recruiter_contact_and_links_job(client, monkeypatch):
    job_id = _job_id(client)

    from seekhunter import api as api_module

    original = api_module._get_job

    def patched(session, jid):
        job, ev = original(session, jid)
        job.contact_name = "Brayden Mackay"
        job.contact_phone = "08 8216 3534"
        session.add(job)
        session.commit()
        return job, ev

    monkeypatch.setattr(api_module, "_get_job", patched)
    client.patch(f"/api/jobs/{job_id}", json={"status": "applied"}, headers=AUTH)

    contacts = client.get("/api/contacts").json()
    assert len(contacts) == 1
    assert contacts[0]["name"] == "Brayden Mackay"
    assert contacts[0]["phone"] == "08 8216 3534"
    assert contacts[0]["job_count"] == 1
    assert contacts[0]["application_count"] == 1


def test_patch_applied_without_contact_name_creates_no_contact(client):
    job_id = _job_id(client)
    client.patch(f"/api/jobs/{job_id}", json={"status": "applied"}, headers=AUTH)
    assert client.get("/api/contacts").json() == []


def test_patch_status_away_from_applied_does_not_delete_application(client):
    job_id = _job_id(client)
    client.patch(f"/api/jobs/{job_id}", json={"status": "applied"}, headers=AUTH)
    client.patch(f"/api/jobs/{job_id}", json={"status": "saved"}, headers=AUTH)
    assert len(client.get("/api/applications").json()) == 1


# ---------------------------------------------------------------------------- JobOut prior_applications


def test_job_out_includes_prior_applications_from_other_jobs_same_company(client):
    with next(client.app.dependency_overrides[get_session]()) as s:
        repo.create_application(s, job_id=None, company="Acme", title="Old Role",
                                applied_at=utcnow())

    job = client.get("/api/jobs").json()[0]
    assert job["application"] is None
    assert len(job["prior_applications"]) == 1
    assert job["prior_applications"][0]["title"] == "Old Role"


def test_job_out_prior_applications_excludes_own_application(client):
    job_id = _job_id(client)
    client.patch(f"/api/jobs/{job_id}", json={"status": "applied"}, headers=AUTH)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["application"] is not None
    assert job["prior_applications"] == []


def test_job_out_prior_applications_capped_at_five_most_recent(client):
    with next(client.app.dependency_overrides[get_session]()) as s:
        for i in range(7):
            repo.create_application(s, job_id=None, company="Acme", title=f"Role {i}",
                                    applied_at=utcnow())

    job = client.get("/api/jobs").json()[0]
    assert len(job["prior_applications"]) == 5


# ---------------------------------------------------------------------------- applications CRUD


def test_create_manual_application_with_inline_contact(client):
    body = {"company": "Globex", "title": "Backend Engineer", "url": "https://x", "notes": "cold applied",
           "contact": {"name": "Jo Smith", "role": "Recruiter", "email": "jo@globex.com"}}
    r = client.post("/api/applications", json=body, headers=AUTH)
    assert r.status_code == 201
    out = r.json()
    assert out["source"] == "manual"
    assert out["company_key"] == company_key("Globex")

    contacts = client.get("/api/contacts").json()
    assert contacts[0]["name"] == "Jo Smith"
    assert contacts[0]["email"] == "jo@globex.com"


def test_create_application_requires_write_token(client):
    r = client.post("/api/applications", json={"company": "Globex", "title": "QA"})
    assert r.status_code == 401


def test_patch_application_stage_and_notes(client):
    r = client.post("/api/applications", json={"company": "Globex", "title": "QA"}, headers=AUTH)
    aid = r.json()["id"]
    r2 = client.patch(f"/api/applications/{aid}", json={"stage": "interview", "notes": "phone screen done"},
                      headers=AUTH)
    assert r2.status_code == 200
    assert r2.json()["stage"] == "interview"
    assert r2.json()["notes"] == "phone screen done"


def test_patch_application_invalid_stage_rejected(client):
    r = client.post("/api/applications", json={"company": "Globex", "title": "QA"}, headers=AUTH)
    aid = r.json()["id"]
    assert client.patch(f"/api/applications/{aid}", json={"stage": "bogus"}, headers=AUTH).status_code == 422


def test_patch_application_not_found(client):
    assert client.patch("/api/applications/999", json={"stage": "interview"}, headers=AUTH).status_code == 404


def test_delete_application(client):
    r = client.post("/api/applications", json={"company": "Globex", "title": "QA"}, headers=AUTH)
    aid = r.json()["id"]
    assert client.delete(f"/api/applications/{aid}", headers=AUTH).status_code == 204
    assert client.get("/api/applications").json() == []


def test_list_applications_filters_by_stage_and_query(client):
    client.post("/api/applications", json={"company": "Globex", "title": "QA"}, headers=AUTH)
    r = client.post("/api/applications", json={"company": "Initech", "title": "Dev"}, headers=AUTH)
    client.patch(f"/api/applications/{r.json()['id']}", json={"stage": "interview"}, headers=AUTH)

    assert len(client.get("/api/applications", params={"stage": "interview"}).json()) == 1
    assert [a["title"] for a in client.get("/api/applications", params={"q": "qa"}).json()] == ["QA"]


# ---------------------------------------------------------------------------- contacts CRUD


def test_create_and_patch_contact(client):
    r = client.post("/api/contacts", json={"name": "Sam Lee", "company": "Acme", "phone": "0400 000 000"},
                    headers=AUTH)
    assert r.status_code == 201
    cid = r.json()["id"]
    r2 = client.patch(f"/api/contacts/{cid}", json={"email": "sam@acme.com"}, headers=AUTH)
    assert r2.json()["email"] == "sam@acme.com"
    assert r2.json()["phone"] == "0400 000 000"


def test_create_contact_merges_with_existing_by_name_and_company(client):
    client.post("/api/contacts", json={"name": "Sam Lee", "company": "Acme", "phone": "0400 000 000"},
               headers=AUTH)
    r = client.post("/api/contacts", json={"name": "sam lee", "company": "Acme", "email": "sam@acme.com"},
                    headers=AUTH)
    assert len(client.get("/api/contacts").json()) == 1
    assert r.json()["phone"] == "0400 000 000"
    assert r.json()["email"] == "sam@acme.com"


def test_get_contact_detail_includes_interactions_jobs_and_applications(client):
    job_id = _job_id(client)
    r = client.post("/api/contacts", json={"name": "Sam Lee", "company": "Acme"}, headers=AUTH)
    cid = r.json()["id"]
    with next(client.app.dependency_overrides[get_session]()) as s:
        from seekhunter.models import Job

        repo.link_contact_job(s, cid, job_id)
        repo.ensure_application_for_job(s, s.get(Job, job_id), utcnow())

    client.post("/api/interactions", json={"contact_id": cid, "kind": "call", "note": "rang"}, headers=AUTH)
    detail = client.get(f"/api/contacts/{cid}").json()
    assert detail["interactions"][0]["kind"] == "call"
    assert detail["jobs"] == [{"id": job_id, "title": "React Dev", "company": "Acme", "url": "u"}]
    assert len(detail["applications"]) == 1


def test_contact_not_found(client):
    assert client.get("/api/contacts/999").status_code == 404
    assert client.patch("/api/contacts/999", json={"notes": "x"}, headers=AUTH).status_code == 404


def test_list_contacts_filters_by_query(client):
    client.post("/api/contacts", json={"name": "Sam Lee", "company": "Acme"}, headers=AUTH)
    client.post("/api/contacts", json={"name": "Jane Doe", "company": "Other"}, headers=AUTH)
    assert [c["name"] for c in client.get("/api/contacts", params={"q": "jane"}).json()] == ["Jane Doe"]


# ---------------------------------------------------------------------------- interactions


def test_create_interaction_requires_contact_or_application(client):
    r = client.post("/api/interactions", json={"kind": "call"}, headers=AUTH)
    assert r.status_code == 422


def test_create_interaction_invalid_kind_rejected(client):
    r = client.post("/api/contacts", json={"name": "Sam Lee"}, headers=AUTH)
    cid = r.json()["id"]
    r2 = client.post("/api/interactions", json={"contact_id": cid, "kind": "carrier_pigeon"}, headers=AUTH)
    assert r2.status_code == 422


def test_create_interaction_unknown_contact_404(client):
    r = client.post("/api/interactions", json={"contact_id": 999, "kind": "call"}, headers=AUTH)
    assert r.status_code == 404


def test_delete_interaction(client):
    r = client.post("/api/contacts", json={"name": "Sam Lee"}, headers=AUTH)
    cid = r.json()["id"]
    r2 = client.post("/api/interactions", json={"contact_id": cid, "kind": "call"}, headers=AUTH)
    iid = r2.json()["id"]
    assert client.delete(f"/api/interactions/{iid}", headers=AUTH).status_code == 204
    assert client.get(f"/api/contacts/{cid}").json()["interactions"] == []


def test_job_contact_log_upserts_contact_and_logs_interaction(client, monkeypatch):
    job_id = _job_id(client)
    from seekhunter import api as api_module

    original = api_module._get_job

    def patched(session, jid):
        job, ev = original(session, jid)
        job.contact_name = "Brayden Mackay"
        session.add(job)
        session.commit()
        return job, ev

    monkeypatch.setattr(api_module, "_get_job", patched)
    r = client.post(f"/api/jobs/{job_id}/contact-log", json={"kind": "call", "note": "left voicemail"},
                    headers=AUTH)
    assert r.status_code == 201
    assert r.json()["kind"] == "call"
    contacts = client.get("/api/contacts").json()
    assert contacts[0]["name"] == "Brayden Mackay"
    assert contacts[0]["interaction_count"] == 1


def test_job_contact_log_without_recruiter_name_422(client):
    job_id = _job_id(client)
    r = client.post(f"/api/jobs/{job_id}/contact-log", json={"kind": "call"}, headers=AUTH)
    assert r.status_code == 422


# ---------------------------------------------------------------------------- companies


def test_companies_endpoint_groups_by_company_key(client):
    with next(client.app.dependency_overrides[get_session]()) as s:
        repo.create_application(s, job_id=None, company="Acme", title="A", applied_at=utcnow())
        repo.create_application(s, job_id=None, company="Acme Pty Ltd", title="B", applied_at=utcnow())

    companies = client.get("/api/companies").json()
    assert len(companies) == 1
    assert companies[0]["application_count"] == 2


# ---------------------------------------------------------------------------- history + summary


def test_history_timeline_newest_first(client):
    with next(client.app.dependency_overrides[get_session]()) as s:
        app = repo.create_application(s, job_id=None, company="Acme", title="Dev", applied_at=utcnow())
        repo.update_application(s, app, stage="interview")

    events = client.get("/api/history").json()
    assert events[0]["kind"] == "stage_changed"
    assert events[1]["kind"] == "created"


def test_history_limit_param(client):
    with next(client.app.dependency_overrides[get_session]()) as s:
        for i in range(5):
            repo.create_application(s, job_id=None, company=f"C{i}", title=f"T{i}", applied_at=utcnow())
    assert len(client.get("/api/history", params={"limit": 2}).json()) == 2


def test_history_summary_is_plain_text_with_stage_counts_and_follow_ups(client):
    with next(client.app.dependency_overrides[get_session]()) as s:
        from datetime import timedelta
        repo.create_application(s, job_id=None, company="Acme", title="Stale",
                                applied_at=utcnow() - timedelta(days=9))

    r = client.get("/api/history/summary", params={"days": 14})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "applied 1" in r.text
    assert "Acme · Stale · 9d" in r.text


def test_history_summary_days_bounded(client):
    assert client.get("/api/history/summary", params={"days": 0}).status_code == 422
    assert client.get("/api/history/summary", params={"days": 91}).status_code == 422
