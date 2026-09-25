"""Database engine/session setup for PostgreSQL."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns() -> None:
    """Bring pre-existing tables up to the current models (no Alembic here).

    `create_all` only creates tables that do not exist yet; a column added to
    an already-imported model would otherwise never reach the database.
    New columns are added as nullable — Python-side defaults keep applying.
    """
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = (
                    f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS '
                    f'"{column.name}" {column.type.compile(dialect=engine.dialect)}'
                )
                if column.server_default is not None:
                    rendered = column.server_default.compile(
                        dialect=engine.dialect, compile_kwargs={"literal_binds": True}
                    )
                    ddl += f" DEFAULT {rendered}"
                conn.execute(text(ddl))
                inspector = inspect(engine)


def init_db() -> None:
    """Enable pgvector, create tables, then add any columns the models gained."""
    from . import models  # noqa: F401  (populate metadata)

    # pgvector must exist before any table declares a Vector column.
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    _add_missing_columns()
