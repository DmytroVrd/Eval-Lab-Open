from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return
    Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent(settings.database_url)
engine = create_async_engine(settings.database_url, future=True)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    # Keeps the app usable on a fresh SQLite database; Alembic remains available
    # for production migrations.
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_runtime_columns)


def _ensure_runtime_columns(connection) -> None:
    inspector = inspect(connection)
    table_names = inspector.get_table_names()
    if "runs" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("runs")}
    if "temperature" not in columns:
        connection.execute(text("ALTER TABLE runs ADD COLUMN temperature FLOAT"))
    if "max_cases" not in columns:
        connection.execute(text("ALTER TABLE runs ADD COLUMN max_cases INTEGER"))

    if "results" not in table_names:
        return

    result_columns = {column["name"] for column in inspector.get_columns("results")}
    if "correctness_score" not in result_columns:
        connection.execute(text("ALTER TABLE results ADD COLUMN correctness_score FLOAT"))
    if "relevance_score" not in result_columns:
        connection.execute(text("ALTER TABLE results ADD COLUMN relevance_score FLOAT"))
    if "completeness_score" not in result_columns:
        connection.execute(text("ALTER TABLE results ADD COLUMN completeness_score FLOAT"))
    if "prompt_quality_score" not in result_columns:
        connection.execute(text("ALTER TABLE results ADD COLUMN prompt_quality_score FLOAT"))
