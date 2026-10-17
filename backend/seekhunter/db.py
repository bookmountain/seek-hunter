from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, event
from sqlmodel import Session, SQLModel, create_engine

from seekhunter.config import get_env


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

    return engine


def init_db(engine: Engine | None = None) -> None:
    from seekhunter import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine or get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
