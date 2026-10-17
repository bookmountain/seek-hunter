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
