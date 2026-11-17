"""Startup migrations: a fresh database gets every table, with the ORM's columns."""

import asyncio
import sqlite3

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

pytest.importorskip("alembic")
pytest.importorskip("aiosqlite")

import ducta_server.db.migrate as migrate  # noqa: E402


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
    import ducta_server.db.models  # noqa: F401 — registers the tables
    from ducta_server.db.base import Base

    db = tmp_path / "ducta.db"
    _migrate(db)
    with sqlite3.connect(db) as conn:
        for name, table in Base.metadata.tables.items():
            have = {row[1] for row in conn.execute(f"PRAGMA table_info({name})")}
            assert have == {col.name for col in table.columns}, name


def _stamp(path, revision):
    with sqlite3.connect(path) as conn:
        conn.execute("update alembic_version set version_num = ?", (revision,))


def test_a_database_from_a_newer_ducta_is_named(tmp_path):
    db = tmp_path / "newer.db"
    _migrate(db)
    _stamp(db, "0099_future")
    with pytest.raises(RuntimeError, match="migrated by a newer Ducta.*0099_future"):
        _migrate(db)


def test_an_older_database_is_backed_up_before_migrating(tmp_path, monkeypatch):
    from alembic.script import ScriptDirectory

    db = tmp_path / "older.db"
    _migrate(db)
    [(current,)] = _version(db)
    # Only one migration exists today: pretend a newer head so this one is "old".
    monkeypatch.setattr(ScriptDirectory, "get_current_head", lambda self: "0002_next")
    _migrate(db)
    backup = tmp_path / f"older.db.bak-{current}"
    assert backup.is_file() and "alembic_version" in _tables(backup)


def test_an_up_to_date_database_is_not_backed_up(tmp_path):
    db = tmp_path / "current.db"
    _migrate(db)
    _migrate(db)
    assert not list(tmp_path.glob("*.bak-*"))


@pytest.mark.parametrize("old", ["0002", "0003", "0004"])
def test_a_database_left_by_ducta_0_2_0_is_restamped_not_refused(tmp_path, old):
    """0.2.0's chain ran to 0004; 0002-0004 were folded into 0001 afterwards. Such a database
    already has 0001's schema: it starts, keeps its rows, and a copy is kept."""
    db = tmp_path / "from_0_2_0.db"
    _migrate(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "insert into users (id, username, email, password_hash) values ('admin', 'admin', 'a@b.c', 'x')"
        )
    _stamp(db, old)

    _migrate(db)  # used to raise "migrated by a newer Ducta (migration 0004)"

    assert _version(db) == [("0001",)]
    with sqlite3.connect(db) as conn:
        assert conn.execute("select username from users").fetchall() == [("admin",)]
    backup = tmp_path / f"from_0_2_0.db.bak-{old}"
    assert backup.is_file()
    assert len(list(tmp_path.glob("*.bak-*"))) == 1  # once, not again for the new mark

    _migrate(db)  # and the next start is the ordinary no-op
    assert _version(db) == [("0001",)]
    assert len(list(tmp_path.glob("*.bak-*"))) == 1
