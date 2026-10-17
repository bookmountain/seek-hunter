from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import repo
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
        job, _ = repo.upsert_job(s, JobData(source="seek", external_id="1", title="React Dev", company="Acme",
                                            location="Adelaide SA", work_type="contract", url="u",
                                            description_html="<p>React</p>"))
        repo.save_evaluation(s, job.id, excluded=False, reasons=[], snippets={}, rule_score=70,
                             llm_score=None, llm_note=None, llm_provider=None, final_score=70,
                             matched_skills=["React"], flags=[])
        bad, _ = repo.upsert_job(s, JobData(source="seek", external_id="2", title="Dev", company="Westpac",
                                            location="Adelaide SA", work_type="contract", url="u2"))
        repo.save_evaluation(s, bad.id, excluded=True, reasons=["bank"], snippets={"bank": "Westpac"},
                             rule_score=60, llm_score=None, llm_note=None, llm_provider=None, final_score=60,
                             matched_skills=[], flags=[])

    def override():
        with Session(engine) as s:
            yield s

    app = create_app(init=False)
    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    get_env.cache_clear()


def test_health_and_spa(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert "spa" in client.get("/jobs/123").text


def test_list_jobs_views(client):
    active = client.get("/api/jobs").json()
    assert [j["title"] for j in active] == ["React Dev"]
    assert active[0]["matched_skills"] == ["React"]
    assert active[0]["city"] == "adelaide"
    excluded = client.get("/api/jobs", params={"view": "excluded"}).json()
    assert excluded[0]["reasons"] == ["bank"]


@pytest.fixture
def multi_city_client(monkeypatch, tmp_path):
    """A second client/engine pair (independent of `client`) seeded with jobs in two cities, for
    the city-filter and /api/jobs/cities tests."""
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
        adelaide, _ = repo.upsert_job(s, JobData(source="seek", external_id="1", title="Adelaide Dev",
                                                 company="Acme", location="Adelaide SA", work_type="contract",
                                                 url="u1"), profile_location="All Adelaide SA")
        repo.save_evaluation(s, adelaide.id, excluded=False, reasons=[], snippets={}, rule_score=50,
                             llm_score=None, llm_note=None, llm_provider=None, final_score=50,
                             matched_skills=[], flags=[])
        melbourne, _ = repo.upsert_job(s, JobData(source="seek", external_id="2", title="Melbourne Dev",
                                                  company="Acme", location="Melbourne VIC",
                                                  work_type="contract", url="u2"),
                                       profile_location="All Melbourne VIC")
        repo.save_evaluation(s, melbourne.id, excluded=False, reasons=[], snippets={}, rule_score=50,
                             llm_score=None, llm_note=None, llm_provider=None, final_score=50,
                             matched_skills=[], flags=[])

    def override():
        with Session(engine) as s:
            yield s

    app = create_app(init=False)
    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    get_env.cache_clear()


def test_list_jobs_city_filter(multi_city_client):
    melbourne = multi_city_client.get("/api/jobs", params={"city": "melbourne"}).json()
    assert [j["title"] for j in melbourne] == ["Melbourne Dev"]
    adelaide = multi_city_client.get("/api/jobs", params={"city": "adelaide"}).json()
    assert [j["title"] for j in adelaide] == ["Adelaide Dev"]


def test_jobs_cities_counts(multi_city_client):
    counts = {row["city"]: row["count"] for row in multi_city_client.get("/api/jobs/cities").json()}
    assert counts == {"adelaide": 1, "melbourne": 1}


def test_job_detail_and_status_update_requires_token(client):
    job_id = client.get("/api/jobs").json()[0]["id"]
    assert "React" in client.get(f"/api/jobs/{job_id}").json()["description_html"]
    assert client.patch(f"/api/jobs/{job_id}", json={"status": "saved"}).status_code == 401
    r = client.patch(f"/api/jobs/{job_id}", json={"status": "saved", "notes": "apply Monday"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "saved"


def test_unexclude_with_allowlist(client):
    job_id = client.get("/api/jobs", params={"view": "excluded"}).json()[0]["id"]
    r = client.post(f"/api/jobs/{job_id}/unexclude", json={"allowlist_employer": True}, headers=AUTH)
    assert r.status_code == 200
    assert "Westpac" in client.get("/api/settings").json()["employer_allowlist"]
    assert len(client.get("/api/jobs").json()) == 2


def test_search_profile_crud_and_settings(client):
    body = {"name": "Mel", "keywords": "react", "location": "All Melbourne VIC", "work_types": [],
           "sources": ["seek"], "enabled": True}
    r = client.post("/api/search-profiles", json=body, headers=AUTH)
    pid = r.json()["id"]
    assert any(p["id"] == pid for p in client.get("/api/search-profiles").json())
    assert client.put(f"/api/search-profiles/{pid}", json={**r.json(), "enabled": False},
                      headers=AUTH).json()["enabled"] is False
    assert client.delete(f"/api/search-profiles/{pid}", headers=AUTH).status_code == 204
    s = client.get("/api/settings").json()
    s["weights"]["full_time"] = 5
    assert client.put("/api/settings", json=s, headers=AUTH).json()["weights"]["full_time"] == 5


def test_runs_list(client):
    assert client.get("/api/runs").json() == []


def test_spa_path_traversal_is_blocked(client):
    r = client.get("/../../../../etc/passwd")
    assert r.status_code == 200
    assert "root:" not in r.text
    assert "spa" in r.text


def test_put_settings_invalid_regex_returns_422(client):
    s = client.get("/api/settings").json()
    s["clearance_patterns"] = ["["]
    assert client.put("/api/settings", json=s, headers=AUTH).status_code == 422


def test_trigger_run_spawns_detached_process(client, monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr("subprocess.Popen", FakePopen)
    r = client.post("/api/runs", headers=AUTH)
    assert r.status_code == 202 and r.json() == {"started": True}
    assert len(calls) == 1


def test_brief_and_summary_are_plain_text(client):
    job_id = client.get("/api/jobs").json()[0]["id"]
    r = client.get(f"/api/jobs/{job_id}/brief")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert r.text.startswith(f"#{job_id} React Dev")
    s = client.get("/api/summary", params={"hours": 24})
    assert s.headers["content-type"].startswith("text/plain")
    assert f"#{job_id}" in s.text
    assert client.get("/api/jobs/99999/brief").status_code == 404


def test_create_app_rejects_weak_token_without_dev_mode(monkeypatch):
    monkeypatch.setenv("SEEKHUNTER_DEV", "0")
    monkeypatch.setenv("API_WRITE_TOKEN", "dev-token")
    get_env.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            create_app(init=False)
    finally:
        get_env.cache_clear()


def test_create_app_accepts_strong_token_without_dev_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("SEEKHUNTER_DEV", "0")
    monkeypatch.setenv("API_WRITE_TOKEN", "a" * 32)
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    get_env.cache_clear()
    try:
        create_app(init=False)
    finally:
        get_env.cache_clear()


def test_spa_null_byte_path_does_not_500(client):
    r = client.get("/a%00b")
    assert r.status_code == 200
    assert "spa" in r.text


def test_spa_bare_api_path_is_404(client):
    assert client.get("/api").status_code == 404


def test_spa_sets_security_headers(client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_jobs_limit_and_offset_are_bounded(client):
    assert client.get("/api/jobs", params={"limit": -1}).status_code == 422
    assert client.get("/api/jobs", params={"limit": 501}).status_code == 422
    assert client.get("/api/jobs", params={"offset": -1}).status_code == 422
    assert client.get("/api/jobs", params={"limit": 10}).status_code == 200


def test_summary_hours_is_bounded(client):
    assert client.get("/api/summary", params={"hours": 0}).status_code == 422
    assert client.get("/api/summary", params={"hours": 721}).status_code == 422
    assert client.get("/api/summary", params={"hours": 24}).status_code == 200


def test_notify_test_message_matches_cli(client, monkeypatch):
    sent = {}

    def fake_send(self, text):
        sent["text"] = text

    monkeypatch.setattr("seekhunter.notify.Notifier.send", fake_send)
    r = client.post("/api/notify/test", headers=AUTH)
    assert r.status_code == 200
    assert sent["text"] == "SeekHunter test message"


def test_job_out_includes_contact_fields_and_search_urls(client):
    active = client.get("/api/jobs").json()
    job = active[0]
    assert job["contact_name"] is None
    assert job["contact_phone"] is None
    assert job["contact_email"] is None
    assert job["contact_linkedin"] is None
    assert job["contact_search"]["linkedin"].startswith(
        "https://www.linkedin.com/search/results/people/?keywords=")
    assert "Acme" in job["contact_search"]["linkedin"]

    detail = client.get(f"/api/jobs/{job['id']}").json()
    assert "contact_search" in detail


def test_job_out_includes_insight_fields_defaulting_to_none(client):
    job = client.get("/api/jobs").json()[0]
    assert job["applicant_count"] is None
    assert job["applicant_volume"] is None
    assert job["resume_pct"] is None
    assert job["cover_letter_pct"] is None
    assert job["insights_checked_at"] is None


def test_brief_includes_competition_line_when_insights_present(client, monkeypatch):
    job_id = client.get("/api/jobs").json()[0]["id"]

    from seekhunter import api as api_module

    original = api_module._get_job

    def patched(session, jid):
        job, ev = original(session, jid)
        job.applicant_count = 77
        job.applicant_volume = "Medium application volume"
        job.resume_pct = 100
        job.cover_letter_pct = 57
        job.insights_checked_at = utcnow()
        return job, ev

    monkeypatch.setattr(api_module, "_get_job", patched)
    r = client.get(f"/api/jobs/{job_id}/brief")
    assert "Competition: 77 applicants (Medium application volume) · 100% resume · 57% cover letter" in r.text
    assert "checked" in r.text


def test_brief_omits_competition_line_when_no_insights(client):
    job_id = client.get("/api/jobs").json()[0]["id"]
    r = client.get(f"/api/jobs/{job_id}/brief")
    assert "Competition:" not in r.text


def test_brief_includes_recruiter_line_when_job_has_contact(client, monkeypatch):
    job_id = client.get("/api/jobs").json()[0]["id"]

    from seekhunter import api as api_module

    original = api_module._get_job

    def patched(session, jid):
        job, ev = original(session, jid)
        job.contact_name = "Brayden Mackay"
        job.contact_phone = "08 8216 3534"
        return job, ev

    monkeypatch.setattr(api_module, "_get_job", patched)
    r = client.get(f"/api/jobs/{job_id}/brief")
    assert "Recruiter: Brayden Mackay · 08 8216 3534" in r.text


def test_unexclude_allowlist_is_case_insensitive_dedupe(client):
    job_id = client.get("/api/jobs", params={"view": "excluded"}).json()[0]["id"]
    client.post(f"/api/jobs/{job_id}/unexclude", json={"allowlist_employer": True}, headers=AUTH)
    settings = client.get("/api/settings").json()
    settings["employer_allowlist"] = ["westpac"]
    client.put("/api/settings", json=settings, headers=AUTH)
    client.post(f"/api/jobs/{job_id}/unexclude", json={"allowlist_employer": True}, headers=AUTH)
    final = client.get("/api/settings").json()["employer_allowlist"]
    assert [e.casefold() for e in final].count("westpac") == 1
