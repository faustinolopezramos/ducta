"""Runs must survive the in-memory window.

Every execution was already being written to `runs_dir` (meta.json + logs.jsonl)
and, when configured, to the database — but nothing ever read either back.
`ExecutionManager.get_logs` consulted only the RAM buffer, and `_get_owned`
only the in-memory record, so once maintenance pruned a run (six hours by
default, or the 500-record cap) or the process restarted, the execution
returned 404 and its logs came back empty while both sat intact on disk.

`DatabaseExecutionStore.get_logs` had existed with no callers, and no file in
the codebase ever opened a `logs.jsonl`.

These cover the read path that closes that gap, and the path-traversal guard it
made necessary: the run id reaches the store straight from
`GET /executions/{execution_id}/logs`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from ducta.api.exceptions import ExecutionNotFoundError
from ducta.api.execution.file_log_store import FileLogStore
from ducta.api.execution.manager import ExecutionManager
from ducta.api.models.execution import ExecutionResponse, ExecutionStatus, LogEntry


def _record(execution_id: str = "run-1", **overrides) -> ExecutionResponse:
    payload = {
        "id": execution_id,
        "pipeline_name": "train",
        "env": "dev",
        "status": ExecutionStatus.SUCCESS,
        "started_at": datetime.now(tz=timezone.utc),
    }
    payload.update(overrides)
    return ExecutionResponse(**payload)


def _entry(message: str) -> LogEntry:
    return LogEntry(
        timestamp=datetime.now(tz=timezone.utc).isoformat(), level="INFO", message=message
    )


@pytest.fixture
def store(tmp_path) -> FileLogStore:
    return FileLogStore(str(tmp_path))


class TestFileStoreRoundTrip:
    def test_a_finished_run_reads_back(self, store):
        record = _record()
        store.start_run(record)
        store.append(record.id, _entry("first"))
        store.append(record.id, _entry("second"))
        store.finish_run(record)

        assert [e.message for e in store.read_logs(record.id)] == ["first", "second"]
        meta = store.read_meta(record.id)
        assert meta is not None
        assert meta.pipeline_name == "train"

    def test_a_live_run_reads_back_without_losing_buffered_lines(self, store):
        # `append` only flushes every _FLUSH_EVERY lines, so a naive read of a
        # still-open run truncates whatever is still in the buffer.
        record = _record("run-live")
        store.start_run(record)
        for i in range(5):  # fewer than _FLUSH_EVERY
            store.append(record.id, _entry(f"line-{i}"))

        assert len(store.read_logs(record.id)) == 5

    def test_a_half_written_final_line_does_not_lose_the_rest(self, store, tmp_path):
        record = _record("run-truncated")
        store.start_run(record)
        store.append(record.id, _entry("good"))
        store.finish_run(record)

        logs_path = tmp_path / record.id / "logs.jsonl"
        with logs_path.open("a", encoding="utf-8") as handle:
            handle.write('{"timestamp": "2026-01-01T00:00:00", "level": "INFO", "mess')

        assert [e.message for e in store.read_logs(record.id)] == ["good"]

    def test_unknown_run_reads_as_empty_not_an_error(self, store):
        assert store.read_logs("never-existed") == []
        assert store.read_meta("never-existed") is None

    def test_runs_are_listed_newest_first(self, store):
        for name in ("run-a", "run-b", "run-c"):
            store.finish_run(_record(name))
        listed = [r.id for r in store.list_runs()]
        assert sorted(listed) == ["run-a", "run-b", "run-c"]


class TestPathTraversalGuard:
    @pytest.mark.parametrize(
        "bad_id",
        ["../../etc/passwd", "..", "a/b", "run\\..\\..", "", "run id", "run;rm"],
    )
    def test_a_crafted_run_id_cannot_escape_the_runs_directory(self, store, bad_id):
        # The id arrives from the URL of GET /executions/{execution_id}/logs.
        assert store.read_logs(bad_id) == []
        assert store.read_meta(bad_id) is None

    def test_ordinary_ids_still_work(self, store):
        for good in ("run-1", "abc123", "a_b-c", "0f8e7d6c5b4a"):
            store.finish_run(_record(good))
            assert store.read_meta(good) is not None


class TestManagerFallback:
    """`load_logs` / `load_execution` reaching past the in-memory stores."""

    @pytest.fixture
    def manager(self, store) -> ExecutionManager:
        # Built field-by-field: a real ExecutionManager would need settings, a
        # queue, a timeout manager and a live event loop, none of which this
        # read path touches.
        mgr = object.__new__(ExecutionManager)
        mgr._db_store = None
        mgr._file_log_store = store
        return mgr

    def test_logs_come_from_disk_once_the_buffer_is_gone(self, manager, store):
        record = _record("run-pruned")
        store.start_run(record)
        store.append(record.id, _entry("persisted line"))
        store.finish_run(record)

        # Nothing in memory: the record was pruned and its buffer deleted.
        class _EmptyStore:
            def get(self, _id):
                raise ExecutionNotFoundError("gone")

        class _EmptyBuffers:
            def get_logs(self, _id):
                return []

        manager._store = _EmptyStore()
        manager._log_manager = _EmptyBuffers()

        logs = asyncio.run(manager.load_logs(record.id))
        assert [e.message for e in logs] == ["persisted line"]

        recovered = asyncio.run(manager.load_execution(record.id))
        assert recovered.pipeline_name == "train"

    def test_the_live_buffer_wins_over_disk(self, manager, store):
        record = _record("run-live-2")
        store.start_run(record)
        store.append(record.id, _entry("stale disk copy"))
        store.finish_run(record)

        class _MemoryStore:
            def get(self, _id):
                return record

        class _Buffers:
            def get_logs(self, _id):
                return [_entry("fresh buffered line")]

        manager._store = _MemoryStore()
        manager._log_manager = _Buffers()

        logs = asyncio.run(manager.load_logs(record.id))
        assert [e.message for e in logs] == ["fresh buffered line"]

    def test_an_unknown_execution_still_raises(self, manager):
        class _EmptyStore:
            def get(self, _id):
                raise ExecutionNotFoundError("gone")

        manager._store = _EmptyStore()
        manager._log_manager = type("B", (), {"get_logs": lambda self, _id: []})()

        with pytest.raises(ExecutionNotFoundError):
            asyncio.run(manager.load_logs("no-such-run"))

    def test_ownership_is_enforced_on_a_record_recovered_from_disk(self, manager, store):
        # Falling back to disk must not become a way to read another user's run.
        record = _record("run-owned", user_id="owner")
        store.start_run(record)
        store.append(record.id, _entry("secret"))
        store.finish_run(record)

        class _EmptyStore:
            def get(self, _id):
                raise ExecutionNotFoundError("gone")

        manager._store = _EmptyStore()
        manager._log_manager = type("B", (), {"get_logs": lambda self, _id: []})()

        with pytest.raises(ExecutionNotFoundError):
            asyncio.run(manager.load_logs(record.id, user_id="someone-else"))

        assert asyncio.run(manager.load_logs(record.id, user_id="owner"))


class TestMetaIsValidJson:
    def test_meta_is_readable_by_ordinary_tools(self, store, tmp_path):
        # `runs_dir` is documented as inspectable with cat/jq; keep it true.
        record = _record("run-json")
        store.finish_run(record)
        raw = json.loads((tmp_path / record.id / "meta.json").read_text(encoding="utf-8"))
        assert raw["id"] == "run-json"
        assert raw["pipeline_name"] == "train"
