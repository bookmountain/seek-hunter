import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from seekhunter import api_radar, repo
from seekhunter.api import create_app
from seekhunter.config import get_env
from seekhunter.db import get_session
from seekhunter.models import Job, RadarCompany
from tests.test_ats_clients import FakeHTTP, Resp

AUTH = {"Authorization": "Bearer t0k"}
SECRET = "s3cret-value"


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    monkeypatch.setenv("API_WRITE_TOKEN", "t0k")
    monkeypatch.setenv("ALLOWED_CIDRS", "127.0.0.1/32,testclient/32")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    monkeypatch.setenv("RADAR_WEBHOOK_SECRET", SECRET)
    get_env.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.ensure_seed(s)
    spawned = []
    monkeypatch.setattr(api_radar, "_spawn_cli", lambda *a: spawned.append(a))
    http = FakeHTTP({})
    monkeypatch.setattr(api_radar, "_radar_http", lambda: http)

    def override():
        with Session(engine) as s:
            yield s

    app = create_app(init=False)
    app.dependency_overrides[get_session] = override
    yield TestClient(app), engine, spawned, http
    get_env.cache_clear()


def _add(engine, **kw):
    with Session(engine) as s:
        c = RadarCompany(**{"name": "Acme", "company_key": "acme", "ats": "greenhouse", "ats_token": "acme",
                            **kw})
        s.add(c)
        s.commit()
        s.refresh(c)
        return c.id


def test_list_and_patch_and_delete(ctx):
    client, engine, _, _ = ctx
    cid = _add(engine)
    rows = client.get("/api/radar/companies").json()
    assert [r["name"] for r in rows] == ["Acme"] and "ignored_ids" not in rows[0]

    assert client.patch(f"/api/radar/companies/{cid}", json={"enabled": False}).status_code == 401
    patch = {"enabled": False, "ats": "lever", "ats_token": "acme2"}
    r = client.patch(f"/api/radar/companies/{cid}", json=patch, headers=AUTH)
    assert r.status_code == 200
    assert (r.json()["enabled"], r.json()["ats"], r.json()["ats_token"]) == (False, "lever", "acme2")
    assert client.patch(f"/api/radar/companies/{cid}", json={"ats": "bogus"}, headers=AUTH).status_code == 422
    assert client.patch(f"/api/radar/companies/{cid}", json={"ats": "workday", "ats_token": "nope"},
                        headers=AUTH).status_code == 422
    assert client.get("/api/radar/companies", params={"enabled": True}).json() == []

    assert client.delete(f"/api/radar/companies/{cid}", headers=AUTH).json() == {"deleted": True}
    assert client.get("/api/radar/companies").json() == []
    assert client.delete(f"/api/radar/companies/{cid}", headers=AUTH).status_code == 404


def test_manual_add_detects_from_careers_page(ctx):
    client, _, _, http = ctx
    http.routes[("GET", "https://acme.example/careers")] = Resp(
        None, 200, '<iframe src="https://boards.greenhouse.io/embed/job_board?for=acmeco"></iframe>')
    r = client.post("/api/radar/companies", json={"name": "Acme Pty Ltd", "careers_url": "https://acme.example/careers"},
                    headers=AUTH)
    assert r.status_code == 201
    body = r.json()
    got = (body["ats"], body["ats_token"], body["source"], body["enabled"])
    assert got == ("greenhouse", "acmeco", "manual", True)
    assert client.post("/api/radar/companies", json={"name": "X", "careers_url": "ftp://x"},
                       headers=AUTH).status_code == 422
    assert client.post("/api/radar/companies", json={"name": "X"}).status_code == 401


def test_manual_add_without_any_board_records_the_miss(ctx):
    client, *_ = ctx
    body = client.post("/api/radar/companies", json={"name": "Nowhere Widgets"}, headers=AUTH).json()
    assert body["ats"] == "other" and body["last_error"]


def test_check_and_seed_spawn_the_cli(ctx):
    client, engine, spawned, _ = ctx
    cid = _add(engine)
    other = _add(engine, name="Beta", company_key="beta", ats="other", ats_token=None)
    assert client.post(f"/api/radar/companies/{cid}/check", headers=AUTH).status_code == 202
    assert client.post(f"/api/radar/companies/{other}/check", headers=AUTH).status_code == 409
    assert client.post("/api/radar/seed", headers=AUTH).status_code == 202
    assert spawned == [("radar", "--company", str(cid)), ("radar", "--seed")]


def _watch(engine):
    return _add(engine, ats="other", ats_token=None, careers_url="https://acme.example/careers",
                city="adelaide")


def test_webhook_rejects_bad_or_missing_secret(ctx, monkeypatch):
    client, engine, spawned, _ = ctx
    _watch(engine)
    url = "/api/radar/webhook/changedetection"
    assert client.post(url, json={}).status_code == 401
    assert client.post(url, params={"secret": "wrong"}, json={}).status_code == 401
    monkeypatch.setenv("RADAR_WEBHOOK_SECRET", "")
    assert client.post(url, params={"secret": ""}, json={}).status_code == 503
    assert spawned == []


def test_webhook_creates_radar_jobs_from_apprise_payload(ctx):
    client, engine, spawned, _ = ctx
    cid = _watch(engine)
    payload = {"version": "1.0", "title": "SeekHunter radar", "type": "info", "message": "\n".join([
        "watch_url: https://acme.example/careers",
        "(added) Senior Software Engineer https://acme.example/careers/123",
        "(added) Office Coordinator",
        "(removed) Graduate Developer",
    ])}
    r = client.post("/api/radar/webhook/changedetection", params={"secret": SECRET}, json=payload)
    assert r.status_code == 202
    body = r.json()
    assert body["matched"] is True and body["company_id"] == cid and body["created"] == 1
    assert spawned == [("radar", "--pending")]
    with Session(engine) as s:
        job = s.exec(select(Job).where(Job.source == "radar")).one()
        assert job.title == "Senior Software Engineer"
        assert job.url == "https://acme.example/careers/123"
        assert job.needs_details and job.city == "adelaide"
    # replay: nothing new, no spawn; header auth works too
    r = client.post("/api/radar/webhook/changedetection", headers={"X-Radar-Secret": SECRET}, json=payload)
    assert r.json()["created"] == 0 and len(spawned) == 1


def test_webhook_unknown_url(ctx):
    client, *_ = ctx
    r = client.post("/api/radar/webhook/changedetection", params={"secret": SECRET},
                    json={"url": "https://nobody.example/jobs", "diff_added": "Software Engineer"})
    assert r.status_code == 202 and r.json()["matched"] is False
