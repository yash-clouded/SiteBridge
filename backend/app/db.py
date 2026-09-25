"""Database engine/session setup for PostgreSQL."""
from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.schema import CreateIndex
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

logger = logging.getLogger(__name__)


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


def _add_missing_foreign_keys() -> None:
    """Attach constraints for columns that were added later.

    `_add_missing_columns` creates the column but not its FK, which would
    leave `ON DELETE SET NULL` (used by review/actuals columns) unenforced
    on databases created before Phase 8.
    """
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {
                (fk["referred_table"], tuple(fk["constrained_columns"]))
                for fk in inspector.get_foreign_keys(table.name)
            }
            for fk in table.foreign_keys:
                local = fk.parent.name
                referred_table = fk.column.table.name
                if (referred_table, (local,)) in existing:
                    continue
                name = fk.constraint.name if fk.constraint else f"fk_{table.name}_{local}"
                on_delete = fk.ondelete or "NO ACTION"
                conn.execute(
                    text(
                        f'ALTER TABLE "{table.name}" ADD CONSTRAINT "{name}" '
                        f'FOREIGN KEY ("{local}") REFERENCES "{referred_table}" '
                        f'("{fk.column.name}") ON DELETE {on_delete}'
                    )
                )
                logger.info("Added FK %s on %s.%s", name, table.name, local)


def _add_missing_indexes() -> None:
    """Create indexes the models declare (e.g. the Phase 8 approval index)."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {ix["name"] for ix in inspector.get_indexes(table.name)}
            for index in table.indexes:
                if not index.name or index.name in existing:
                    continue
                conn.execute(CreateIndex(index))
                logger.info("Added index %s on %s", index.name, table.name)


def init_db() -> None:
    """Enable pgvector, create tables, then add any columns the models gained."""
    from . import models  # noqa: F401  (populate metadata)

    # pgvector must exist before any table declares a Vector column.
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    _add_missing_columns()
    _add_missing_foreign_keys()
    _add_missing_indexes()
