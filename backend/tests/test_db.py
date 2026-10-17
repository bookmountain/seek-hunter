from sqlalchemy import create_engine, inspect, text
from sqlmodel import Session, select

from seekhunter.db import CONTACT_COLUMNS, INSIGHT_COLUMNS, init_db
from seekhunter.domain import JobData
from seekhunter.models import Job
from seekhunter.repo import upsert_job

OLD_JOBS_TABLE = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    source VARCHAR NOT NULL,
    external_id VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    company VARCHAR NOT NULL,
    location VARCHAR NOT NULL,
    work_type VARCHAR NOT NULL,
    salary_label VARCHAR,
    listed_at DATETIME,
    url VARCHAR NOT NULL,
    teaser VARCHAR NOT NULL,
    description_html VARCHAR NOT NULL,
    dedupe_key VARCHAR NOT NULL,
    canonical_job_id INTEGER,
    first_seen_at DATETIME NOT NULL,
    status VARCHAR NOT NULL,
    notes VARCHAR NOT NULL,
    force_include BOOLEAN NOT NULL,
    notified_at DATETIME
)
"""


def test_init_db_adds_missing_contact_columns_and_keeps_existing_rows(tmp_path):
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(OLD_JOBS_TABLE))
        conn.execute(text(
            "INSERT INTO jobs (id, source, external_id, title, company, location, work_type, url, "
            "teaser, description_html, dedupe_key, first_seen_at, status, notes, force_include) "
            "VALUES (1, 'seek', '1', 'Dev', 'Acme', 'Adelaide SA', 'full_time', 'u', '', '', "
            "'dev|acme', '2026-01-01 00:00:00', 'new', '', 0)"
        ))

    init_db(engine)

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("jobs")}
    assert set(CONTACT_COLUMNS) <= cols

    with Session(engine) as s:
        job = s.exec(select(Job).where(Job.id == 1)).one()
        assert job.title == "Dev"
        assert job.company == "Acme"
        assert job.contact_name is None
        assert job.contact_phone is None


def test_init_db_is_idempotent_when_columns_already_exist(tmp_path):
    db_path = tmp_path / "new.db"
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(engine)
    init_db(engine)  # must not raise on a second run
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("jobs")}
    assert set(CONTACT_COLUMNS) <= cols


def test_init_db_on_fresh_database_creates_contact_columns(tmp_path):
    db_path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(engine)
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("jobs")}
    assert set(CONTACT_COLUMNS) <= cols


def test_init_db_adds_missing_insight_columns_and_keeps_existing_rows(tmp_path):
    db_path = tmp_path / "old_insights.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(OLD_JOBS_TABLE))
        conn.execute(text(
            "INSERT INTO jobs (id, source, external_id, title, company, location, work_type, url, "
            "teaser, description_html, dedupe_key, first_seen_at, status, notes, force_include) "
            "VALUES (1, 'seek', '1', 'Dev', 'Acme', 'Adelaide SA', 'full_time', 'u', '', '', "
            "'dev|acme', '2026-01-01 00:00:00', 'new', '', 0)"
        ))

    init_db(engine)

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("jobs")}
    assert set(INSIGHT_COLUMNS) <= cols

    with Session(engine) as s:
        job = s.exec(select(Job).where(Job.id == 1)).one()
        assert job.title == "Dev"
        assert job.applicant_count is None
        assert job.insights_checked_at is None


def test_init_db_is_idempotent_for_insight_columns(tmp_path):
    db_path = tmp_path / "idempotent_insights.db"
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(engine)
    init_db(engine)  # must not raise on a second run
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("jobs")}
    assert set(INSIGHT_COLUMNS) <= cols


def test_init_db_insight_columns_roundtrip(tmp_path):
    db_path = tmp_path / "roundtrip_insights.db"
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(engine)
    with Session(engine) as s:
        job = Job(source="seek", external_id="1", title="Dev", company="Acme", location="Adelaide SA",
                  work_type="full_time", url="u", dedupe_key="dev|acme", applicant_count=77,
                  applicant_volume="Medium application volume", resume_pct=100, cover_letter_pct=57)
        s.add(job)
        s.commit()
        s.refresh(job)
        assert job.applicant_count == 77
        assert job.applicant_volume == "Medium application volume"
        assert job.resume_pct == 100
        assert job.cover_letter_pct == 57


def test_init_db_creates_tailorings_table_on_existing_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text(OLD_JOBS_TABLE))
    init_db(engine)
    inspector = inspect(engine)
    assert "tailorings" in inspector.get_table_names()
    cols = {c["name"] for c in inspector.get_columns("tailorings")}
    assert {"job_id", "status", "progress", "warnings", "result", "resume_hash", "out_dir",
            "send_requested", "sent_at"} <= cols


def test_init_db_adds_city_column_and_backfills_from_location(tmp_path):
    db_path = tmp_path / "old_city.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(OLD_JOBS_TABLE))
        conn.execute(text(
            "INSERT INTO jobs (id, source, external_id, title, company, location, work_type, url, "
            "teaser, description_html, dedupe_key, first_seen_at, status, notes, force_include) "
            "VALUES (1, 'seek', '1', 'Dev', 'Acme', 'Melbourne VIC', 'full_time', 'u', '', '', "
            "'dev|acme', '2026-01-01 00:00:00', 'new', '', 0)"
        ))
        conn.execute(text(
            "INSERT INTO jobs (id, source, external_id, title, company, location, work_type, url, "
            "teaser, description_html, dedupe_key, first_seen_at, status, notes, force_include) "
            "VALUES (2, 'seek', '2', 'QA', 'Acme', 'Remote', 'full_time', 'u', '', '', "
            "'qa|acme', '2026-01-01 00:00:00', 'new', '', 0)"
        ))

    init_db(engine)

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("jobs")}
    assert "city" in cols

    with Session(engine) as s:
        melbourne_job = s.exec(select(Job).where(Job.id == 1)).one()
        assert melbourne_job.city == "melbourne"
        unrecognized_job = s.exec(select(Job).where(Job.id == 2)).one()
        assert unrecognized_job.city == "adelaide"  # migration default


def test_init_db_city_backfill_is_idempotent_and_does_not_clobber_existing_city(tmp_path):
    db_path = tmp_path / "idempotent_city.db"
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(engine)
    with Session(engine) as s:
        job, _ = upsert_job(s, JobData(source="seek", external_id="1", title="Dev", company="Acme",
                                       location="Sydney NSW", work_type="full_time", url="u"))
        assert job.city == "sydney"

    init_db(engine)  # must not raise, and must not touch the already-set city
    with Session(engine) as s:
        job = s.exec(select(Job).where(Job.external_id == "1")).one()
        assert job.city == "sydney"


def test_init_db_on_fresh_database_creates_city_column(tmp_path):
    db_path = tmp_path / "fresh_city.db"
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(engine)
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("jobs")}
    assert "city" in cols
