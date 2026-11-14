"""`DatabaseExecutionStore` against a real SQLite database (aiosqlite).

`test_user_store_db.py` covers the "no DATABASE_URL" path; this covers what the
store does when persistence is on: what it writes, reads back, batches and prunes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from ducta_server.db import migrate  # noqa: E402
from ducta_server.db import session as session_module  # noqa: E402
from ducta_server.db.engine import enforce_sqlite_foreign_keys  # noqa: E402
from ducta_server.db.models import ExecutionLogRow  # noqa: E402
from ducta_server.db.stores import execution_store as store_module  # noqa: E402
from ducta_server.db.stores.execution_store import DatabaseExecutionStore  # noqa: E402
from ducta_server.exceptions import ExecutionNotFoundError  # noqa: E402
from ducta_server.models.execution import (  # noqa: E402
    ExecutionResponse,
    ExecutionStatus,
    LogEntry,
)

NOW = datetime.now(tz=timezone.utc).replace(microsecond=0)


def _record(id_: str, status=ExecutionStatus.RUNNING, **fields) -> ExecutionResponse:
    return ExecutionResponse(
        id=id_,
        pipeline_name=fields.pop("pipeline_name", "etl"),
        env="dev",
        status=status,
        started_at=fields.pop("started_at", NOW),
        **fields,
    )


def _log(message: str, offset: int = 0) -> LogEntry:
    return LogEntry(
        timestamp=NOW + timedelta(seconds=offset),
        level="INFO",
        message=message,
        extra={"node": "load"} if offset == 0 else {},
    )


def run(tmp_path, monkeypatch, scenario, **store_kwargs):
    """Run *scenario(store, factory)* on a fresh SQLite database, in one event loop.

    The schema comes from Ducta's own migrations, as the server builds it.
    """
    monkeypatch.setattr(migrate, "_migrations_run", False)

    async def main():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ducta.db'}")
        enforce_sqlite_foreign_keys(engine)  # as get_engine() does for SQLite
        await migrate.run_migrations(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(session_module, "get_session_factory", lambda: factory)
        monkeypatch.setattr(store_module, "get_session_factory", lambda: factory)
        try:
            return await scenario(DatabaseExecutionStore(engine, **store_kwargs), factory)
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def _log_rows(factory) -> int:
    async with factory() as s:
        return (await s.execute(select(func.count()).select_from(ExecutionLogRow))).scalar_one()


def test_a_record_reads_back_as_written(tmp_path, monkeypatch):
    async def scenario(store, _):
        await store.add(_record("a", model_version="3", sweep_id="s", sweep_index=2))
        return await store.get("a")

    got = run(tmp_path, monkeypatch, scenario)

    assert (got.id, got.pipeline_name, got.env, got.status) == ("a", "etl", "dev", "running")
    assert (got.model_version, got.sweep_id, got.sweep_index) == ("3", "s", 2)


def test_update_moves_a_run_to_its_outcome(tmp_path, monkeypatch):
    async def scenario(store, _):
        await store.add(_record("a"))
        finished = NOW + timedelta(seconds=30)
        await store.update(
            _record(
                "a",
                ExecutionStatus.FAILED,
                finished_at=finished,
                exit_code=4,
                duration_seconds=30.0,
                error_message="node load failed",
            )
        )
        return await store.get("a")

    got = run(tmp_path, monkeypatch, scenario)

    assert got.status == ExecutionStatus.FAILED
    assert (got.exit_code, got.duration_seconds, got.error_message) == (4, 30.0, "node load failed")


def test_update_of_an_unknown_run_inserts_it(tmp_path, monkeypatch):
    async def scenario(store, _):
        await store.update(_record("late", ExecutionStatus.SUCCESS))
        return await store.contains("late")

    assert run(tmp_path, monkeypatch, scenario) is True


def test_a_missing_run_is_not_found(tmp_path, monkeypatch):
    async def scenario(store, _):
        with pytest.raises(ExecutionNotFoundError):
            await store.get("nope")
        return await store.peek("nope"), await store.contains("nope")

    assert run(tmp_path, monkeypatch, scenario) == (None, False)


def test_list_is_newest_first_filtered_and_paged(tmp_path, monkeypatch):
    async def scenario(store, _):
        for i, name in enumerate(["etl", "ml", "etl", "etl"]):
            await store.add(_record(f"r{i}", pipeline_name=name, started_at=NOW + timedelta(i)))
        return (
            [r.id for r in await store.list_all()],
            [r.id for r in await store.list_all(pipeline_name="etl")],
            [r.id for r in await store.list_all(pipeline_name="etl", limit=1, offset=1)],
        )

    everything, etl, page = run(tmp_path, monkeypatch, scenario)

    assert everything == ["r3", "r2", "r1", "r0"]
    assert etl == ["r3", "r2", "r0"]
    assert page == ["r2"]


def test_log_lines_are_batched_then_flushed_in_order(tmp_path, monkeypatch):
    async def scenario(store, factory):
        await store.add(_record("a"))
        for i in range(3):
            await store.append_log("a", _log(f"line {i}", offset=i))
        before_batch = await _log_rows(factory)  # 3 < batch of 4: still buffered
        await store.append_log("a", _log("line 3", offset=3))
        after_batch = await _log_rows(factory)
        await store.append_log("a", _log("line 4", offset=4))
        await store.flush_logs("a")
        return before_batch, after_batch, await store.get_logs("a")

    before, after, logs = run(tmp_path, monkeypatch, scenario, log_batch_size=4)

    assert (before, after) == (0, 4)
    assert [entry.message for entry in logs] == [f"line {i}" for i in range(5)]
    assert logs[0].extra == {"node": "load"} and logs[1].extra == {}


def test_logs_are_paged(tmp_path, monkeypatch):
    async def scenario(store, _):
        await store.add(_record("a"))
        for i in range(5):
            await store.append_log("a", _log(f"line {i}", offset=i))
        await store.flush_logs("a")
        return await store.get_logs("a", limit=2, offset=2)

    assert [e.message for e in run(tmp_path, monkeypatch, scenario)] == ["line 2", "line 3"]


def test_prune_removes_only_finished_runs_older_than_the_retention(tmp_path, monkeypatch):
    old = NOW - timedelta(days=10)

    async def scenario(store, _):
        await store.add(_record("old-success", ExecutionStatus.SUCCESS, finished_at=old))
        await store.add(_record("old-failed", ExecutionStatus.FAILED, finished_at=old))
        await store.add(_record("new-success", ExecutionStatus.SUCCESS, finished_at=NOW))
        await store.add(_record("old-running", ExecutionStatus.RUNNING, finished_at=old))
        deleted = await store.prune_stale(retention_seconds=timedelta(days=1).total_seconds())
        return deleted, sorted(r.id for r in await store.list_all())

    deleted, left = run(tmp_path, monkeypatch, scenario)

    assert deleted == 2
    assert left == ["new-success", "old-running"]


def test_pruning_a_run_removes_its_logs(tmp_path, monkeypatch):
    # SQLite cascades only with PRAGMA foreign_keys=ON, which get_engine() sets.
    async def scenario(store, factory):
        await store.add(_record("a", ExecutionStatus.SUCCESS, finished_at=NOW - timedelta(days=10)))
        await store.append_log("a", _log("line"))
        await store.flush_logs("a")
        await store.prune_stale(retention_seconds=60)
        return await _log_rows(factory)

    assert run(tmp_path, monkeypatch, scenario) == 0


def test_without_a_database_every_call_is_a_no_op(monkeypatch):
    monkeypatch.setattr(session_module, "get_session_factory", lambda: None)
    monkeypatch.setattr(store_module, "get_session_factory", lambda: None)
    store = DatabaseExecutionStore(engine=None)  # type: ignore[arg-type]

    async def scenario():
        await store.add(_record("a"))
        await store.append_log("a", _log("line"))
        return (
            await store.list_all(),
            await store.get_logs("a"),
            await store.prune_stale(60),
            await store.peek("a"),
        )

    assert asyncio.run(scenario()) == ([], [], 0, None)


def test_the_application_engine_turns_sqlite_foreign_keys_on(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy import text

    from ducta_server.db import engine as engine_module

    url = f"sqlite+aiosqlite:///{tmp_path / 'ducta.db'}"
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(
        engine_module, "get_settings", lambda: SimpleNamespace(database_url=url, debug=False)
    )

    async def pragma():
        engine = engine_module.get_engine()
        try:
            async with engine.connect() as conn:
                return (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one()
        finally:
            await engine.dispose()

    assert asyncio.run(pragma()) == 1
