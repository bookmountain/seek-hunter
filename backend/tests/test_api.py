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
    excluded = client.get("/api/jobs", params={"view": "excluded"}).json()
    assert excluded[0]["reasons"] == ["bank"]


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
