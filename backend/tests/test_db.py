from sqlalchemy import create_engine, inspect, text
from sqlmodel import Session, select

from seekhunter.db import CONTACT_COLUMNS, init_db
from seekhunter.models import Job

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
