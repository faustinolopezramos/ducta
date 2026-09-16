"""Listing executions must reach past the in-memory window.

`GET /executions` listed only the in-memory store, which keeps a run for six
hours (or until the 500-record cap, or a restart) while its `meta.json` stays in
`runs_dir`. A single run could be opened by id long after it had disappeared
from the list — and anything counting runs over a day or a week, like the
dashboard, silently undercounted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ducta.api.execution.file_log_store import FileLogStore
from ducta.api.execution.manager import ExecutionManager
from ducta.api.models.execution import ExecutionResponse, ExecutionStatus

NOW = datetime.now(tz=timezone.utc)


def _record(execution_id: str, **overrides) -> ExecutionResponse:
    payload = {
        "id": execution_id,
        "pipeline_name": "ml.student_performance",
        "project_id": "batch",
        "env": "dev",
        "status": ExecutionStatus.SUCCESS,
        "started_at": NOW,
    }
    payload.update(overrides)
    return ExecutionResponse(**payload)


class _MemoryStore:
    def __init__(self, records=()):
        self._records = list(records)

    def list_all(self):
        return sorted(self._records, key=lambda e: e.started_at, reverse=True)


@pytest.fixture
def store(tmp_path) -> FileLogStore:
    return FileLogStore(str(tmp_path))


def _manager(memory, file_store) -> ExecutionManager:
    # Built field-by-field, as in test_execution_log_persistence: the list path
    # touches only the two stores.
    mgr = object.__new__(ExecutionManager)
    mgr._store = _MemoryStore(memory)
    mgr._file_log_store = file_store
    mgr._db_store = None
    return mgr


class TestListingIncludesPersistedRuns:
    def test_a_run_pruned_from_memory_is_still_listed(self, store):
        store.finish_run(_record("old", started_at=NOW - timedelta(days=2)))
        mgr = _manager([_record("live")], store)

        runs, total = mgr.list_executions_paginated()

        assert total == 2
        assert [r.id for r in runs] == ["live", "old"]  # newest first across both

    def test_the_in_memory_copy_wins_over_its_file(self, store):
        store.finish_run(_record("run-1", status=ExecutionStatus.RUNNING))
        mgr = _manager([_record("run-1", status=ExecutionStatus.FAILED)], store)

        runs = mgr.list_executions()

        assert len(runs) == 1
        assert runs[0].status == ExecutionStatus.FAILED

    def test_ownership_still_applies_to_persisted_runs(self, store):
        store.finish_run(_record("theirs", user_id="owner"))
        mgr = _manager([], store)

        assert mgr.list_executions(user_id="someone-else") == []
        assert [r.id for r in mgr.list_executions(user_id="owner")] == ["theirs"]

    def test_time_filters_reach_persisted_runs(self, store):
        store.finish_run(_record("yesterday", started_at=NOW - timedelta(hours=20)))
        store.finish_run(_record("last-week", started_at=NOW - timedelta(days=8)))
        mgr = _manager([], store)

        since = (NOW - timedelta(days=7)).isoformat()
        runs, _ = mgr.list_executions_paginated(since=since)

        assert [r.id for r in runs] == ["yesterday"]

    def test_filters_apply_to_persisted_runs(self, store):
        store.finish_run(_record("other-project", project_id="streaming"))
        store.finish_run(_record("this-project"))
        mgr = _manager([], store)

        runs, _ = mgr.list_executions_paginated(project_id="batch")

        assert [r.id for r in runs] == ["this-project"]

    def test_without_a_runs_dir_only_memory_is_listed(self):
        mgr = _manager([_record("live")], None)
        assert [r.id for r in mgr.list_executions()] == ["live"]
