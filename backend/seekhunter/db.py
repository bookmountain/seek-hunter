from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, event, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from seekhunter.config import get_env

CONTACT_COLUMNS = ("contact_name", "contact_phone", "contact_email", "contact_linkedin")
INSIGHT_COLUMNS = ("applicant_count", "applicant_volume", "resume_pct", "cover_letter_pct",
                   "insights_checked_at")
_INSIGHT_COLUMN_TYPES = {
    "applicant_count": "INTEGER", "applicant_volume": "VARCHAR", "resume_pct": "INTEGER",
    "cover_letter_pct": "INTEGER", "insights_checked_at": "DATETIME",
}


@lru_cache
def get_engine() -> Engine:
    env = get_env()
    if env.database_url.startswith("sqlite:///"):
        from pathlib import Path

        Path(env.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(env.database_url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _wal(dbapi_conn, _):  # noqa: ANN001
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")

    return engine


def init_db(engine: Engine | None = None) -> None:
    from seekhunter import models  # noqa: F401  (register tables)

    eng = engine or get_engine()
    SQLModel.metadata.create_all(eng)
    _ensure_contact_columns(eng)
    _ensure_insight_columns(eng)


def _ensure_columns(engine: Engine, columns: tuple[str, ...], sql_type: str | dict[str, str]) -> None:
    """`create_all` never alters an existing table, so columns added after a `jobs` table already
    existed are migrated here by hand: idempotent, additive `ALTER TABLE ... ADD COLUMN`."""
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("jobs")}
    missing = [c for c in columns if c not in existing]
    if not missing:
        return
    with engine.begin() as conn:
        for column in missing:
            column_type = sql_type[column] if isinstance(sql_type, dict) else sql_type
            conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {column} {column_type}"))


def _ensure_contact_columns(engine: Engine) -> None:
    _ensure_columns(engine, CONTACT_COLUMNS, "VARCHAR")


def _ensure_insight_columns(engine: Engine) -> None:
    _ensure_columns(engine, INSIGHT_COLUMNS, _INSIGHT_COLUMN_TYPES)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
