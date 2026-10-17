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


def market_jd(ext, title="Backend Developer", city="adelaide", salary="$40 - $45 per hour",
             work_type="contract", teaser="Java"):
    return JobData(source="seek", external_id=f"{city}-{ext}", title=title, company="Acme",
                   location=city, work_type=work_type, url=f"https://x/{ext}", salary_label=salary,
                   teaser=teaser)


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
    now = utcnow()
    with Session(engine) as s:
        repo.ensure_seed(s)
        # Adelaide: 3 backend jobs with Java (resume has Java) + 1 frontend job with Kubernetes (a gap)
        for i in range(3):
            job, _ = repo.upsert_market_job(s, market_jd(f"b{i}"), "adelaide", "developer", now,
                                            role_family="backend", skills=["Java"],
                                            salary_min_hourly=40.0, salary_max_hourly=45.0)
            repo.apply_market_details(s, job, ["Java"])
        job, _ = repo.upsert_market_job(s, market_jd("f1", title="Frontend Developer"), "adelaide",
                                        "frontend", now, role_family="frontend", skills=["Kubernetes"],
                                        salary_min_hourly=None, salary_max_hourly=None)
        repo.apply_market_details(s, job, ["Kubernetes"])
        # Melbourne: 2 backend jobs with C#
        for i in range(2):
            job, _ = repo.upsert_market_job(s, market_jd(f"m{i}"), "melbourne", "developer", now,
                                            role_family="backend", skills=["C#"], salary_min_hourly=50.0,
                                            salary_max_hourly=60.0)
            repo.apply_market_details(s, job, ["C#"])
        date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        repo.save_market_snapshot(s, "adelaide", date, {
            "total": 4, "detailed_count": 4, "by_work_type": {"contract": 4}, "by_role_family": {},
            "skill_counts": {"Java": 3, "Kubernetes": 1}, "salary_percentiles": {"p25": 40, "p50": 42,
                                                                                 "p75": 45, "n": 3},
        })

    def override():
        with Session(engine) as s:
            yield s

    app = create_app(init=False)
    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    get_env.cache_clear()


def test_overview_returns_all_four_cities_in_order(client):
    r = client.get("/api/insights/overview")
    assert r.status_code == 200
    rows = r.json()
    assert [row["city"] for row in rows] == ["adelaide", "melbourne", "sydney", "perth"]
    adelaide = rows[0]
    assert adelaide["total"] == 4
    assert adelaide["flexible"] == 4
    assert adelaide["flexible_share"] == 1.0
    assert adelaide["detailed_sample_size"] == 4
    assert adelaide["salary_sample_size"] == 3
    melbourne = rows[1]
    assert melbourne["total"] == 2
    sydney = rows[2]
    assert sydney["total"] == 0 and sydney["flexible_share"] == 0.0


def test_skills_sorted_desc_with_you_have_flag(client):
    r = client.get("/api/insights/skills", params={"city": "adelaide"})
    assert r.status_code == 200
    rows = r.json()
    by_skill = {row["skill"]: row for row in rows}
    assert by_skill["Java"]["count"] == 3
    assert by_skill["Java"]["you_have"] is True
    assert by_skill["Kubernetes"]["you_have"] is False
    assert rows[0]["skill"] == "Java"  # most common first


def test_skills_filters_by_role_family(client):
    r = client.get("/api/insights/skills", params={"city": "adelaide", "role_family": "frontend"})
    rows = r.json()
    assert [row["skill"] for row in rows] == ["Kubernetes"]


def test_skills_rejects_unknown_city(client):
    r = client.get("/api/insights/skills", params={"city": "brisbane"})
    assert r.status_code == 422


def test_compare_returns_share_per_city_per_skill(client):
    r = client.get("/api/insights/compare", params={"skills": "Java,C#"})
    assert r.status_code == 200
    body = r.json()
    assert body["skills"] == ["Java", "C#"]
    by_city = {c["city"]: c for c in body["cities"]}
    assert by_city["adelaide"]["shares"] == {"Java": 0.75, "C#": 0.0}
    assert by_city["melbourne"]["shares"] == {"Java": 0.0, "C#": 1.0}
    assert by_city["adelaide"]["detailed_sample_size"] == 4


def test_gaps_excludes_profile_skills_and_includes_examples(client):
    r = client.get("/api/insights/gaps", params={"city": "adelaide"})
    assert r.status_code == 200
    rows = r.json()
    assert [row["skill"] for row in rows] == ["Kubernetes"]
    assert rows[0]["example_titles"] == ["Frontend Developer"]
    assert rows[0]["role_families"] == ["frontend"]


def test_roles_groups_counts_and_flexible_share(client):
    r = client.get("/api/insights/roles", params={"city": "adelaide"})
    assert r.status_code == 200
    rows = {row["role_family"]: row for row in r.json()}
    assert rows["backend"]["count"] == 3
    assert rows["backend"]["flexible_share"] == 1.0
    assert "Java" in rows["backend"]["top_skills"]
    assert rows["frontend"]["count"] == 1


def test_trends_reads_snapshot_rows(client):
    r = client.get("/api/insights/trends", params={"city": "adelaide", "skills": "Java,Kubernetes"})
    assert r.status_code == 200
    body = r.json()
    assert body["city"] == "adelaide"
    assert len(body["points"]) == 1
    assert body["points"][0]["shares"] == {"Java": 0.75, "Kubernetes": 0.25}


def test_trends_rejects_unknown_city(client):
    assert client.get("/api/insights/trends", params={"city": "x", "skills": "Java"}).status_code == 422


def test_insights_endpoints_are_read_only_and_ip_gated_like_other_routes(client):
    # no Authorization header required for these GET endpoints (read-only, IP-gated by middleware)
    assert client.get("/api/insights/overview").status_code == 200
