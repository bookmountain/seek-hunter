from dataclasses import replace
from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import repo
from seekhunter.domain import JobData
from seekhunter.http import SourceBlocked
from seekhunter.market import (
    compare,
    gaps,
    normalize_salary_hourly,
    overview,
    role_family,
    roles,
    run_market_crawl,
    skill_demand,
    trends,
    write_snapshot,
)
from seekhunter.models import utcnow
from seekhunter.settings_model import AppSettings


@pytest.mark.parametrize(
    "title,expected",
    [
        ("AI Engineer", "ai_ml"),
        ("Machine Learning Engineer", "ai_ml"),
        ("Senior ML Engineer", "ai_ml"),
        ("LLM Platform Engineer", "ai_ml"),
        ("Data Scientist", "ai_ml"),
        ("Data Engineer", "data"),
        ("Data Analyst", "data"),
        ("Analytics Lead", "data"),
        ("BI Developer", "data"),
        ("ETL Developer", "data"),
        ("DevOps Engineer", "devops_cloud"),
        ("Cloud Engineer", "devops_cloud"),
        ("Platform Engineer", "devops_cloud"),
        ("SRE", "devops_cloud"),
        ("Infrastructure Engineer", "devops_cloud"),
        ("iOS Developer", "mobile"),
        ("Android Developer", "mobile"),
        ("Mobile App Developer", "mobile"),
        ("React Native Developer", "mobile"),
        ("Flutter Developer", "mobile"),
        ("QA Engineer", "qa"),
        ("Test Analyst", "qa"),
        ("Automation Tester", "qa"),
        ("Quality Assurance Lead", "qa"),
        ("IT Support Officer", "it_support"),
        ("Helpdesk Technician", "it_support"),
        ("Help Desk Analyst", "it_support"),
        ("Service Desk Analyst", "it_support"),
        ("Desktop Support Engineer", "it_support"),
        ("Technician", "it_support"),
        ("Frontend Developer", "frontend"),
        ("Front End Engineer", "frontend"),
        ("Front-End Developer", "frontend"),
        ("UI Developer", "frontend"),
        ("Backend Developer", "backend"),
        ("Back End Engineer", "backend"),
        ("Back-End Developer", "backend"),
        ("API Developer", "backend"),
        ("Full Stack Developer", "fullstack"),
        ("Fullstack Engineer", "fullstack"),
        ("Full-Stack Developer", "fullstack"),
        ("Software Engineer", "fullstack"),
        ("Software Developer", "fullstack"),
        ("Developer", "fullstack"),
        ("Programmer", "fullstack"),
        ("Warehouse Picker", "other"),
        ("Retail Assistant", "other"),
    ],
)
def test_role_family_rules(title, expected):
    assert role_family(title) == expected


def test_role_family_ai_takes_priority_over_developer():
    assert role_family("AI Engineer / Developer") == "ai_ml"


def test_role_family_frontend_takes_priority_over_fullstack():
    assert role_family("Frontend Developer") == "frontend"


def test_role_family_word_boundary_avoids_false_positives():
    # "ai" must not match inside other words
    assert role_family("Rail Infrastructure Maintainer") != "ai_ml"


def test_role_family_case_insensitive():
    assert role_family("devops engineer") == "devops_cloud"
    assert role_family("DEVOPS ENGINEER") == "devops_cloud"


@pytest.mark.parametrize(
    "label,expected_min,expected_max",
    [
        ("$40 – $45 per hour", 40.0, 45.0),
        ("$90 - $110 p.h.", 90.0, 110.0),
        ("$650 per day", 650 / 7.6, 650 / 7.6),
        ("$120,000 - $140,000 + super", 120000 / 1976, 140000 / 1976),
        ("$110k–$125k", 110000 / 1976, 125000 / 1976),
        ("Up to $95k", None, 95000 / 1976),
        ("Competitive salary", None, None),
        (None, None, None),
    ],
)
def test_normalize_salary_hourly(label, expected_min, expected_max):
    lo, hi = normalize_salary_hourly(label)
    if expected_min is None:
        assert lo is None
    else:
        assert lo == pytest.approx(expected_min, rel=1e-4)
    if expected_max is None:
        assert hi is None
    else:
        assert hi == pytest.approx(expected_max, rel=1e-4)


def test_normalize_salary_hourly_ignores_ambiguous_small_number():
    assert normalize_salary_hourly("$50 negotiable") == (None, None)


# ------------------------------------------------------------------ market crawl


class FakeSeekSource:
    def __init__(self, jobs_by_location, details_by_id=None, blocked_search_locations=frozenset(),
                detail_blocked=False):
        self.jobs_by_location = jobs_by_location
        self.details_by_id = details_by_id or {}
        self.blocked_search_locations = blocked_search_locations
        self.detail_blocked = detail_blocked
        self.client = type("C", (), {"request_count": 0, "blocked_count": 0})()
        self.search_calls = []
        self.detail_calls = []

    def search(self, profile, max_pages, daterange=7):
        self.search_calls.append((profile.location, profile.keywords, max_pages, daterange))
        if profile.location in self.blocked_search_locations:
            raise SourceBlocked("403")
        return list(self.jobs_by_location.get(profile.location, []))

    def details(self, job):
        self.detail_calls.append(job.external_id)
        if self.detail_blocked:
            raise SourceBlocked("403")
        extra = self.details_by_id.get(job.external_id)
        return replace(job, description_html=extra) if extra else job


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def jd(ext, title="Backend Developer", salary="$40 - $45 per hour", teaser="Java"):
    return JobData(source="seek", external_id=ext, title=title, company="Acme", location="Adelaide SA",
                   work_type="contract", url=f"https://x/{ext}", salary_label=salary, teaser=teaser)


def test_run_market_crawl_upserts_jobs_with_role_and_salary(session):
    settings = AppSettings(market_keywords=["developer"], market_details_per_city=10)
    source = FakeSeekSource({"All Adelaide SA": [jd(f"m{i}") for i in range(3)]})
    report = run_market_crawl(session, source, settings, cities=["adelaide"], now=utcnow())
    assert report["adelaide"]["found"] == 3
    assert report["adelaide"]["new"] == 3

    jobs = repo.market_jobs_scope(session, city="adelaide")
    assert len(jobs) == 3
    assert all(j.role_family == "backend" for j in jobs)
    assert all(j.salary_min_hourly == 40.0 and j.salary_max_hourly == 45.0 for j in jobs)
    assert all(j.skills == ["Java"] for j in jobs)


def test_run_market_crawl_bumps_last_seen_without_duplicating(session):
    settings = AppSettings(market_keywords=["developer"])
    source = FakeSeekSource({"All Adelaide SA": [jd("m1")]})
    first = utcnow()
    run_market_crawl(session, source, settings, cities=["adelaide"], now=first)
    later = first + timedelta(hours=3)
    report = run_market_crawl(session, source, settings, cities=["adelaide"], now=later)
    assert report["adelaide"]["new"] == 0

    jobs = repo.market_jobs_scope(session, city="adelaide")
    assert len(jobs) == 1
    assert jobs[0].last_seen_at == later
    assert jobs[0].first_seen_at == first


def test_run_market_crawl_caps_details_per_city(session):
    settings = AppSettings(market_keywords=["developer"], market_details_per_city=2)
    source = FakeSeekSource({"All Adelaide SA": [jd(f"m{i}") for i in range(5)]})
    run_market_crawl(session, source, settings, cities=["adelaide"], now=utcnow())
    assert len(source.detail_calls) == 2
    detailed = [j for j in repo.market_jobs_scope(session, city="adelaide") if j.details_fetched]
    assert len(detailed) == 2


def test_run_market_crawl_details_extend_skills_from_description(session):
    settings = AppSettings(market_keywords=["developer"], market_details_per_city=10)
    source = FakeSeekSource({"All Adelaide SA": [jd("m1", teaser="Java")]},
                            details_by_id={"m1": "<p>Also needs AWS and Kubernetes</p>"})
    run_market_crawl(session, source, settings, cities=["adelaide"], now=utcnow())
    job = repo.market_jobs_scope(session, city="adelaide")[0]
    assert job.details_fetched is True
    assert set(job.skills) == {"Java", "AWS", "Kubernetes"}


def test_run_market_crawl_writes_snapshot_row(session):
    settings = AppSettings(market_keywords=["developer"], market_details_per_city=10)
    source = FakeSeekSource({"All Adelaide SA": [jd(f"m{i}") for i in range(4)]})
    run_market_crawl(session, source, settings, cities=["adelaide"], now=utcnow())
    snaps = repo.market_snapshots_scope(session, "adelaide")
    assert len(snaps) == 1
    assert snaps[0].total == 4
    assert snaps[0].detailed_count == 4
    assert snaps[0].skill_counts == {"Java": 4}


def test_run_market_crawl_never_touches_jobs_table(session):
    settings = AppSettings(market_keywords=["developer"])
    source = FakeSeekSource({"All Adelaide SA": [jd("m1")]})
    run_market_crawl(session, source, settings, cities=["adelaide"], now=utcnow())
    assert repo.list_jobs(session) == []


def test_run_market_crawl_dry_run_makes_no_database_writes(session):
    settings = AppSettings(market_keywords=["developer"])
    source = FakeSeekSource({"All Adelaide SA": [jd("m1")]})
    report = run_market_crawl(session, source, settings, cities=["adelaide"], now=utcnow(), dry_run=True)
    assert report["adelaide"]["found"] == 1
    assert repo.market_jobs_scope(session, city="adelaide") == []
    assert repo.market_snapshots_scope(session, "adelaide") == []


def test_run_market_crawl_uses_daterange_fourteen_and_two_pages(session):
    settings = AppSettings(market_keywords=["developer"])
    source = FakeSeekSource({"All Adelaide SA": []})
    run_market_crawl(session, source, settings, cities=["adelaide"], now=utcnow())
    assert source.search_calls == [("All Adelaide SA", "developer", 2, 14)]


def test_run_market_crawl_search_blocked_sets_error_and_continues_other_cities(session):
    settings = AppSettings(market_keywords=["developer"])
    source = FakeSeekSource({"All Perth WA": [jd("p1")]}, blocked_search_locations={"All Adelaide SA"})
    report = run_market_crawl(session, source, settings, cities=["adelaide", "perth"], now=utcnow())
    assert report["adelaide"]["error"]
    assert repo.market_jobs_scope(session, city="adelaide") == []
    assert len(repo.market_jobs_scope(session, city="perth")) == 1


# ------------------------------------------------------------------ analysis


def _seed(session, city, now, n=4, role="backend", salary="$40 - $45 per hour", detailed=True,
         skills=("Java",), work_type="contract"):
    jobs = []
    for i in range(n):
        data = JobData(source="seek", external_id=f"{city}-{role}-{i}", title="Backend Developer",
                       company="Acme", location=city, work_type=work_type, url="u", salary_label=salary,
                       teaser=" ".join(skills))
        job, _ = repo.upsert_market_job(session, data, city, "developer", now, role_family=role,
                                        skills=list(skills), salary_min_hourly=40.0, salary_max_hourly=45.0)
        if detailed:
            repo.apply_market_details(session, job, list(skills))
        jobs.append(job)
    return jobs


def test_overview_computes_totals_flexible_share_and_salary(session):
    now = utcnow()
    _seed(session, "adelaide", now, n=3, work_type="contract")
    _seed(session, "melbourne", now, n=1, work_type="full_time")
    rows = {r["city"]: r for r in overview(session, days=14)}
    assert rows["adelaide"]["total"] == 3
    assert rows["adelaide"]["flexible"] == 3
    assert rows["adelaide"]["flexible_share"] == 1.0
    assert rows["adelaide"]["salary_p50"] == pytest.approx(42.5)
    assert rows["sydney"]["total"] == 0 and rows["sydney"]["flexible_share"] == 0.0


def test_skill_demand_share_and_you_have(session):
    now = utcnow()
    _seed(session, "adelaide", now, n=4, skills=("Java", "SQL"))
    rows = {r["skill"]: r for r in skill_demand(session, "adelaide", days=14, profile_skills={"Java"})}
    assert rows["Java"]["count"] == 4 and rows["Java"]["share"] == 1.0 and rows["Java"]["you_have"] is True
    assert rows["SQL"]["you_have"] is False


def test_skill_demand_filters_by_role_family(session):
    now = utcnow()
    _seed(session, "adelaide", now, n=2, role="backend", skills=("Java",))
    _seed(session, "adelaide", now, n=2, role="frontend", skills=("React",))
    rows = skill_demand(session, "adelaide", days=14, role_family="frontend")
    assert [r["skill"] for r in rows] == ["React"]


def test_gaps_excludes_profile_skills_and_includes_examples(session):
    now = utcnow()
    _seed(session, "adelaide", now, n=3, skills=("Kubernetes",))
    rows = gaps(session, "adelaide", days=14, profile_skills={"Java"})
    assert rows[0]["skill"] == "Kubernetes"
    assert rows[0]["count"] == 3
    assert rows[0]["example_titles"] == ["Backend Developer"]
    assert rows[0]["role_families"] == ["backend"]


def test_gaps_excludes_skill_already_in_profile(session):
    now = utcnow()
    _seed(session, "adelaide", now, n=2, skills=("Java",))
    assert gaps(session, "adelaide", days=14, profile_skills={"Java"}) == []


def test_compare_returns_share_per_city_for_each_skill(session):
    now = utcnow()
    _seed(session, "adelaide", now, n=2, skills=("Java",))
    _seed(session, "melbourne", now, n=4, skills=("C#",))
    rows = {r["city"]: r for r in compare(session, ["Java", "C#"], days=14)}
    assert rows["adelaide"]["shares"] == {"Java": 1.0, "C#": 0.0}
    assert rows["melbourne"]["shares"] == {"Java": 0.0, "C#": 1.0}
    assert rows["sydney"]["detailed_sample_size"] == 0


def test_roles_groups_by_family_with_flexible_share_and_top_skills(session):
    now = utcnow()
    _seed(session, "adelaide", now, n=2, role="backend", skills=("Java", "SQL"), work_type="contract")
    _seed(session, "adelaide", now, n=1, role="frontend", skills=("React",), work_type="full_time")
    rows = {r["role_family"]: r for r in roles(session, "adelaide", days=14)}
    assert rows["backend"]["count"] == 2
    assert rows["backend"]["flexible_share"] == 1.0
    assert set(rows["backend"]["top_skills"]) == {"Java", "SQL"}
    assert rows["frontend"]["flexible_share"] == 0.0


def test_trends_reads_from_snapshots_not_live_jobs(session):
    now = utcnow()
    _seed(session, "adelaide", now, n=4, skills=("Java",))
    write_snapshot(session, "adelaide", now)
    # live-only change after the snapshot must not affect trend points
    _seed(session, "adelaide", now, n=4, skills=("C#",))

    points = trends(session, "adelaide", ["Java", "C#"], weeks=8)
    assert len(points) == 1
    assert points[0]["shares"] == {"Java": 1.0, "C#": 0.0}


def test_trends_empty_before_any_snapshot(session):
    assert trends(session, "adelaide", ["Java"], weeks=8) == []
