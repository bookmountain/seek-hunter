from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import repo
from seekhunter.domain import JobData
from seekhunter.models import utcnow


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def data(ext="1", source="seek", title="Dev", company="Acme"):
    return JobData(source=source, external_id=ext, title=title, company=company, location="Adelaide SA",
                   work_type="part_time", url=f"https://x/{ext}")


def test_upsert_marks_new_once(session):
    job, is_new = repo.upsert_job(session, data())
    assert is_new and job.id is not None
    job2, is_new2 = repo.upsert_job(session, data())
    assert not is_new2 and job2.id == job.id


def test_set_contacts_updates_only_given_fields(session):
    job, _ = repo.upsert_job(session, data())
    repo.set_contacts(session, job, name="Brayden Mackay", phone="08 8216 3534")
    session.refresh(job)
    assert job.contact_name == "Brayden Mackay"
    assert job.contact_phone == "08 8216 3534"
    assert job.contact_email is None
    assert job.contact_linkedin is None

    repo.set_contacts(session, job, linkedin="https://www.linkedin.com/in/brayden")
    session.refresh(job)
    assert job.contact_name == "Brayden Mackay"
    assert job.contact_linkedin == "https://www.linkedin.com/in/brayden"


def test_update_job_details_fills_contact_phone_and_email_without_clobbering(session):
    job, _ = repo.upsert_job(session, data())
    job.contact_phone = "0412 345 678"
    session.add(job)
    session.commit()

    repo.update_job_details(session, job, JobData(
        source="seek", external_id="1", title="Dev", company="Acme", location="Adelaide SA",
        work_type="part_time", url="https://x/1", contact_phone="08 8216 3534",
        contact_email="jobs@acme.com"))
    session.refresh(job)
    assert job.contact_phone == "0412 345 678"  # existing value preserved
    assert job.contact_email == "jobs@acme.com"


def test_settings_roundtrip_and_seed(session):
    repo.ensure_seed(session)
    s = repo.load_settings(session)
    s.employer_allowlist = ["Acme"]
    repo.save_settings(session, s)
    assert repo.load_settings(session).employer_allowlist == ["Acme"]
    profiles = repo.list_search_profiles(session)
    assert any(p.keywords == "software engineer" for p in profiles)
    repo.ensure_seed(session)
    assert len(repo.list_search_profiles(session)) == len(profiles)


def test_find_duplicate_across_sources(session):
    seek_job, _ = repo.upsert_job(session, data(ext="1", source="seek", title="Full Stack Developer",
                                                company="Acme Pty Ltd"))
    jora_job, _ = repo.upsert_job(session, data(ext="abc", source="jora", title="Full-Stack Developer",
                                                company="ACME"))
    assert repo.find_duplicate(session, jora_job) == seek_job.id


def test_find_duplicate_ignores_blank_company(session):
    seek_job, _ = repo.upsert_job(session, data(ext="1", source="seek", title="Developer", company=""))
    jora_job, _ = repo.upsert_job(session, data(ext="abc", source="jora", title="Developer", company=""))
    assert seek_job.dedupe_key.endswith("|")
    assert repo.find_duplicate(session, jora_job) is None


def test_find_duplicate_ignores_blank_title(session):
    seek_job, _ = repo.upsert_job(session, data(ext="1", source="seek", title="", company="Acme"))
    jora_job, _ = repo.upsert_job(session, data(ext="abc", source="jora", title="", company="Acme"))
    assert seek_job.dedupe_key.startswith("|")
    assert repo.find_duplicate(session, jora_job) is None


def _with_eval(session, ext, title="Dev", company="Acme", excluded=False, score=50):
    job, _ = repo.upsert_job(session, data(ext=ext, title=title, company=company))
    repo.save_evaluation(session, job.id, excluded=excluded, reasons=[], snippets={}, rule_score=score,
                         llm_score=None, llm_note=None, llm_provider=None, final_score=score,
                         matched_skills=[], flags=[])
    return job


def test_list_jobs_active_excludes_excluded_hidden_and_duplicate(session):
    active = _with_eval(session, "active", title="A")
    excluded = _with_eval(session, "excluded", title="B", excluded=True)
    hidden = _with_eval(session, "hidden", title="C")
    hidden.status = "hidden"
    session.add(hidden)
    session.commit()
    dup = _with_eval(session, "dup", title="D")
    dup.canonical_job_id = active.id
    session.add(dup)
    session.commit()

    results = repo.list_jobs(session, view="active")
    ids = {j.id for j, _ in results}
    assert ids == {active.id}
    assert excluded.id not in ids
    assert hidden.id not in ids
    assert dup.id not in ids


def test_list_jobs_force_include_moves_excluded_job_into_active(session):
    excluded = _with_eval(session, "forced", title="E", excluded=True)
    excluded.force_include = True
    session.add(excluded)
    session.commit()

    ids = {j.id for j, _ in repo.list_jobs(session, view="active")}
    assert excluded.id in ids


def test_list_jobs_status_hidden_returns_hidden_jobs(session):
    hidden = _with_eval(session, "hid2", title="F")
    hidden.status = "hidden"
    session.add(hidden)
    session.commit()

    ids = {j.id for j, _ in repo.list_jobs(session, view="active", status="hidden")}
    assert ids == {hidden.id}


def test_count_excluded_since_ignores_force_include(session):
    excluded = _with_eval(session, "forced2", title="G", excluded=True)
    excluded.force_include = True
    session.add(excluded)
    session.commit()
    _with_eval(session, "excluded2", title="H", excluded=True)

    assert repo.count_excluded_since(session, utcnow() - timedelta(days=1)) == 1


def test_list_jobs_query_percent_matches_nothing_literal(session):
    _with_eval(session, "pct", title="Developer", company="Acme")

    assert repo.list_jobs(session, view="active", q="%") == []


def test_notification_candidates(session):
    j, _ = repo.upsert_job(session, data())
    repo.save_evaluation(session, j.id, excluded=False, reasons=[], snippets={}, rule_score=70,
                         llm_score=None, llm_note=None, llm_provider=None, final_score=70,
                         matched_skills=[], flags=[])
    old, _ = repo.upsert_job(session, data(ext="2"))
    old.first_seen_at = utcnow() - timedelta(days=3)
    session.add(old)
    session.commit()
    repo.save_evaluation(session, old.id, excluded=False, reasons=[], snippets={}, rule_score=90,
                         llm_score=None, llm_note=None, llm_provider=None, final_score=90,
                         matched_skills=[], flags=[])
    cands = repo.notification_candidates(session, utcnow())
    assert [c[0].id for c in cands] == [j.id]
    repo.mark_notified(session, [j.id], utcnow())
    assert repo.notification_candidates(session, utcnow()) == []


def test_set_insights_applies_data_and_checked_at(session):
    job, _ = repo.upsert_job(session, data())
    now = utcnow()
    repo.set_insights(session, job, {
        "applicant_count": 77, "applicant_volume": "Medium application volume",
        "resume_pct": 100, "cover_letter_pct": 57,
    }, now)
    session.refresh(job)
    assert job.applicant_count == 77
    assert job.applicant_volume == "Medium application volume"
    assert job.resume_pct == 100
    assert job.cover_letter_pct == 57
    assert job.insights_checked_at == now


def test_set_insights_with_none_data_still_records_checked_at(session):
    job, _ = repo.upsert_job(session, data())
    now = utcnow()
    repo.set_insights(session, job, None, now)
    session.refresh(job)
    assert job.applicant_count is None
    assert job.insights_checked_at == now


def test_set_insights_with_empty_dict_records_checked_at_without_clobbering(session):
    job, _ = repo.upsert_job(session, data())
    repo.set_insights(session, job, {"applicant_count": 5}, utcnow())
    later = utcnow() + timedelta(minutes=1)
    repo.set_insights(session, job, {}, later)
    session.refresh(job)
    assert job.applicant_count == 5  # not clobbered by an empty refresh result
    assert job.insights_checked_at == later


def test_jobs_needing_insights_only_seek_canonical_not_hidden_within_window(session):
    seek_job, _ = repo.upsert_job(session, data(ext="s1", source="seek"))
    jora_job, _ = repo.upsert_job(session, data(ext="j1", source="jora"))
    hidden, _ = repo.upsert_job(session, data(ext="s2", source="seek"))
    hidden.status = "hidden"
    session.add(hidden)
    dup, _ = repo.upsert_job(session, data(ext="s3", source="seek"))
    dup.canonical_job_id = seek_job.id
    session.add(dup)
    old, _ = repo.upsert_job(session, data(ext="s4", source="seek"))
    old.first_seen_at = utcnow() - timedelta(days=8)
    session.add(old)
    session.commit()

    jobs = repo.jobs_needing_insights(session, utcnow(), limit=10)
    ids = {j.id for j in jobs}
    assert ids == {seek_job.id}
    assert jora_job.id not in ids


def test_jobs_needing_insights_skips_recently_checked(session):
    job, _ = repo.upsert_job(session, data(ext="s1", source="seek"))
    repo.set_insights(session, job, {}, utcnow())
    assert repo.jobs_needing_insights(session, utcnow(), limit=10) == []

    stale_time = utcnow() - timedelta(hours=4)
    repo.set_insights(session, job, {}, stale_time)
    jobs = repo.jobs_needing_insights(session, utcnow(), limit=10)
    assert [j.id for j in jobs] == [job.id]


def test_jobs_needing_insights_orders_nulls_first_then_oldest_checked(session):
    checked, _ = repo.upsert_job(session, data(ext="s1", source="seek"))
    repo.set_insights(session, checked, {}, utcnow() - timedelta(hours=5))
    never_checked, _ = repo.upsert_job(session, data(ext="s2", source="seek"))

    jobs = repo.jobs_needing_insights(session, utcnow(), limit=10)
    assert [j.id for j in jobs] == [never_checked.id, checked.id]


def test_jobs_needing_insights_respects_limit(session):
    for i in range(5):
        repo.upsert_job(session, data(ext=f"s{i}", source="seek"))
    jobs = repo.jobs_needing_insights(session, utcnow(), limit=2)
    assert len(jobs) == 2


def market_data(ext="m1", title="Backend Developer", company="Acme", salary="$40 - $45 per hour"):
    return JobData(source="seek", external_id=ext, title=title, company=company, location="Adelaide SA",
                   work_type="contract", url=f"https://x/{ext}", salary_label=salary, teaser="Java SQL")


def test_upsert_market_job_creates_once_then_bumps_last_seen(session):
    now = utcnow()
    job, is_new = repo.upsert_market_job(session, market_data(), "adelaide", "developer", now,
                                         role_family="backend", skills=["Java", "SQL"],
                                         salary_min_hourly=40.0, salary_max_hourly=45.0)
    assert is_new and job.city == "adelaide" and job.skills == ["Java", "SQL"]
    assert job.role_family == "backend"
    assert job.salary_min_hourly == 40.0 and job.salary_max_hourly == 45.0

    later = now + timedelta(hours=2)
    job2, is_new2 = repo.upsert_market_job(session, market_data(), "adelaide", "developer", later,
                                           role_family="backend", skills=["Java", "SQL"],
                                           salary_min_hourly=40.0, salary_max_hourly=45.0)
    assert not is_new2 and job2.id == job.id
    assert job2.last_seen_at == later
    assert job2.first_seen_at == now


def test_upsert_market_job_never_touches_jobs_table(session):
    repo.upsert_market_job(session, market_data(), "adelaide", "developer", utcnow(), role_family="backend",
                           skills=[], salary_min_hourly=None, salary_max_hourly=None)
    assert repo.list_jobs(session) == []


def test_apply_market_details_sets_skills_and_flag(session):
    job, _ = repo.upsert_market_job(session, market_data(), "adelaide", "developer", utcnow(),
                                    role_family="backend", skills=["Java"], salary_min_hourly=None,
                                    salary_max_hourly=None)
    repo.apply_market_details(session, job, ["Java", "SQL", "AWS"])
    session.refresh(job)
    assert job.details_fetched is True
    assert job.skills == ["Java", "SQL", "AWS"]


def test_market_jobs_needing_details_excludes_detailed_and_respects_limit(session):
    for i in range(3):
        job, _ = repo.upsert_market_job(session, market_data(ext=f"d{i}"), "adelaide", "developer", utcnow(),
                                        role_family="backend", skills=[], salary_min_hourly=None,
                                        salary_max_hourly=None)
    repo.apply_market_details(session, job, ["Java"])  # mark the last one detailed
    pending = repo.market_jobs_needing_details(session, "adelaide", limit=10)
    assert {j.external_id for j in pending} == {"d0", "d1"}

    pending_capped = repo.market_jobs_needing_details(session, "adelaide", limit=1)
    assert len(pending_capped) == 1


def test_market_jobs_needing_details_filters_by_city(session):
    repo.upsert_market_job(session, market_data(ext="a1"), "adelaide", "developer", utcnow(),
                           role_family="backend", skills=[], salary_min_hourly=None, salary_max_hourly=None)
    repo.upsert_market_job(session, market_data(ext="p1"), "perth", "developer", utcnow(),
                           role_family="backend", skills=[], salary_min_hourly=None, salary_max_hourly=None)
    pending = repo.market_jobs_needing_details(session, "perth", limit=10)
    assert [j.external_id for j in pending] == ["p1"]


def test_to_market_jobdata_round_trips_external_id(session):
    job, _ = repo.upsert_market_job(session, market_data(ext="j1"), "adelaide", "developer", utcnow(),
                                    role_family="backend", skills=[], salary_min_hourly=None,
                                    salary_max_hourly=None)
    jd = repo.to_market_jobdata(job)
    assert jd.source == "seek" and jd.external_id == "j1" and jd.title == "Backend Developer"


def test_market_jobs_scope_filters_city_since_role_family_and_detailed(session):
    now = utcnow()
    old = now - timedelta(days=30)
    recent_backend, _ = repo.upsert_market_job(session, market_data(ext="r1"), "adelaide", "developer", now,
                                               role_family="backend", skills=["Java"], salary_min_hourly=None,
                                               salary_max_hourly=None)
    repo.apply_market_details(session, recent_backend, ["Java"])
    repo.upsert_market_job(session, market_data(ext="r2"), "adelaide", "developer", now, role_family="data",
                           skills=[], salary_min_hourly=None, salary_max_hourly=None)
    stale, _ = repo.upsert_market_job(session, market_data(ext="r3"), "adelaide", "developer", old,
                                      role_family="backend", skills=[], salary_min_hourly=None,
                                      salary_max_hourly=None)

    since = now - timedelta(days=1)
    all_recent = repo.market_jobs_scope(session, city="adelaide", since=since)
    assert {j.external_id for j in all_recent} == {"r1", "r2"}

    backend_only = repo.market_jobs_scope(session, city="adelaide", since=since, role_family="backend")
    assert [j.external_id for j in backend_only] == ["r1"]

    detailed_only = repo.market_jobs_scope(session, city="adelaide", since=since, detailed_only=True)
    assert [j.external_id for j in detailed_only] == ["r1"]

    assert stale.external_id == "r3"  # kept, just outside the `since` window used above


def test_save_and_scope_market_snapshots(session):
    date1 = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    stats = {"total": 10, "detailed_count": 4, "by_work_type": {"contract": 10}, "by_role_family": {},
             "skill_counts": {"Java": 3}, "salary_percentiles": {"p25": 40.0, "p50": 45.0, "p75": 50.0,
                                                                 "n": 5}}
    repo.save_market_snapshot(session, "adelaide", date1, stats)
    # re-saving the same (city, date) updates in place, not a second row
    repo.save_market_snapshot(session, "adelaide", date1, {**stats, "total": 11})

    rows = repo.market_snapshots_scope(session, "adelaide")
    assert len(rows) == 1
    assert rows[0].total == 11
    assert rows[0].skill_counts == {"Java": 3}
