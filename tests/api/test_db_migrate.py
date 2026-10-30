"""Startup migrations: a fresh database gets every table, with the ORM's columns."""

import asyncio
import sqlite3

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

pytest.importorskip("alembic")
pytest.importorskip("aiosqlite")

import ducta.api.db.migrate as migrate  # noqa: E402


def _migrate(path):
    migrate._migrations_run = False

    async def go():
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        try:
            await migrate.run_migrations(engine)
        finally:
            await engine.dispose()

    asyncio.run(go())


def _tables(path):
    with sqlite3.connect(path) as conn:
        return {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}


def _version(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("select version_num from alembic_version").fetchall()


def test_fresh_database_gets_every_table(tmp_path):
    db = tmp_path / "fresh.db"
    _migrate(db)
    assert {"executions", "execution_logs", "users", "alembic_version"} <= _tables(db)
    assert len(_version(db)) == 1


def test_running_twice_is_a_no_op(tmp_path):
    db = tmp_path / "twice.db"
    _migrate(db)
    first = _version(db)
    _migrate(db)
    assert _version(db) == first


def test_the_migrated_schema_is_the_orm_schema(tmp_path):
    """One migration builds the whole schema: every ORM table and column, nothing else."""
    import ducta.api.db.models  # noqa: F401 — registers the tables
    from ducta.api.db.base import Base

    db = tmp_path / "ducta.db"
    _migrate(db)
    with sqlite3.connect(db) as conn:
        for name, table in Base.metadata.tables.items():
            have = {row[1] for row in conn.execute(f"PRAGMA table_info({name})")}
            assert have == {col.name for col in table.columns}, name
