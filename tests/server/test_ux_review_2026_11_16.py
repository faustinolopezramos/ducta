"""UX review 2026-11-16: the history must agree with itself.

* Runs started from the CLI have a certificate and no server record: Runs and
  Certificates showed nothing while Health (reading certificates) showed them.
* A run a previous server left queued or running stayed "pending" forever.
* The stream page read "running" from the journal of a run that was over.
* With authentication off, the web app still asked for credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ducta_server.execution import cli_runs
from ducta_server.execution.file_log_store import FileLogStore
from ducta_server.execution.manager import ExecutionManager
from ducta_server.execution.manager_reads import as_interrupted_if_orphaned
from ducta_server.models.execution import (
    ExecutionResponse,
    ExecutionStatus,
    StreamingPipelineStatus,
    StreamingStatusResponse,
)

NOW = datetime.now(tz=timezone.utc)


def _record(execution_id: str, **overrides) -> ExecutionResponse:
    payload = {
        "id": execution_id,
        "pipeline_name": "silver.clean",
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
        return list(self._records)

    def contains(self, execution_id):
        return any(r.id == execution_id for r in self._records)


def _manager(memory, file_store) -> ExecutionManager:
    mgr = object.__new__(ExecutionManager)
    mgr._store = _MemoryStore(memory)
    mgr._file_log_store = file_store
    mgr._db_store = None
    return mgr


def _certificate(runs_dir, run_id, pipeline="silver.clean", status="success", started=NOW):
    run = runs_dir / run_id
    run.mkdir(parents=True)
    (run / "certificate.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "pipeline": pipeline,
                "status": status,
                "environment_name": "dev",
                "started_at": started.isoformat(),
                "ended_at": (started + timedelta(seconds=3)).isoformat(),
                "duration_seconds": 3.0,
                "error": None,
            }
        )
    )


@pytest.fixture(autouse=True)
def _fresh_cache():
    cli_runs.clear_cache()
    yield
    cli_runs.clear_cache()


class TestCliRuns:
    def test_a_certificate_becomes_a_cli_run(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs"
        _certificate(runs, "abc123", status="failed")
        monkeypatch.setattr(cli_runs, "_runs_dirs", lambda _p: [("dev", runs)])

        [run] = cli_runs.project_cli_runs("batch", tmp_path, tmp_path)

        assert run.origin == "cli"
        assert run.id == run.certificate_run_id == "abc123"
        assert run.status == ExecutionStatus.FAILED
        assert run.env == "dev" and run.project_id == "batch"
        assert run.duration_seconds == 3.0

    def test_unfinished_and_unknown_statuses(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs"
        _certificate(runs, "r1", status="running")
        _certificate(runs, "r2", status="something-new")
        monkeypatch.setattr(cli_runs, "_runs_dirs", lambda _p: [("dev", runs)])

        by_id = {r.id: r.status for r in cli_runs.project_cli_runs("batch", tmp_path, tmp_path)}

        assert by_id == {"r1": ExecutionStatus.INTERRUPTED, "r2": ExecutionStatus.FAILED}

    def test_a_directory_is_read_again_only_when_it_changes(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs"
        _certificate(runs, "r1")
        monkeypatch.setattr(cli_runs, "_runs_dirs", lambda _p: [("dev", runs)])
        assert len(cli_runs.project_cli_runs("batch", tmp_path, tmp_path)) == 1

        _certificate(runs, "r2")

        assert len(cli_runs.project_cli_runs("batch", tmp_path, tmp_path)) == 2

    def test_listing_merges_cli_runs_without_duplicating_server_runs(self, tmp_path, monkeypatch):
        server_run = _record("exec-1", certificate_run_id="cert-1", workspace=str(tmp_path))
        mgr = _manager([server_run], None)
        cli = [
            _record("cert-1", origin="cli", certificate_run_id="cert-1"),
            _record(
                "cert-2",
                origin="cli",
                certificate_run_id="cert-2",
                started_at=NOW - timedelta(days=1),
            ),
        ]

        def fake(workspace, known):
            return [r for r in cli if r.id not in known]

        monkeypatch.setattr(cli_runs, "workspace_cli_runs", fake)
        monkeypatch.setattr("ducta_server.execution.manager_reads._project_ids", lambda _w: None)

        runs, total = mgr.list_executions_paginated(workspace=tmp_path)

        assert total == 2
        assert [(r.id, r.origin) for r in runs] == [("exec-1", "server"), ("cert-2", "cli")]

    def test_without_a_workspace_nothing_is_merged(self, monkeypatch):
        monkeypatch.setattr(
            cli_runs, "workspace_cli_runs", lambda *_a: pytest.fail("must not scan")
        )
        mgr = _manager([_record("exec-1")], None)

        _runs, total = mgr.list_executions_paginated()

        assert total == 1


class TestOrphanedRuns:
    def test_unfinished_record_without_owner_is_interrupted(self):
        record = _record("x", status=ExecutionStatus.PENDING)

        settled = as_interrupted_if_orphaned(record, None)

        assert settled.status == ExecutionStatus.INTERRUPTED
        assert "server stopped" in (settled.error_message or "")

    def test_a_dead_owner_means_interrupted(self):
        record = _record("x", status=ExecutionStatus.RUNNING)
        owner = {"pid": 2**22 + 12345, "host": os.uname().nodename}

        assert as_interrupted_if_orphaned(record, owner).status == ExecutionStatus.INTERRUPTED

    def test_a_live_other_process_on_this_host_keeps_its_run(self):
        import socket

        record = _record("x", status=ExecutionStatus.RUNNING)
        owner = {"pid": os.getppid(), "host": socket.gethostname()}

        assert as_interrupted_if_orphaned(record, owner).status == ExecutionStatus.RUNNING

    def test_another_machine_is_left_alone(self):
        record = _record("x", status=ExecutionStatus.PENDING)

        settled = as_interrupted_if_orphaned(record, {"pid": 1, "host": "elsewhere.invalid"})

        assert settled.status == ExecutionStatus.PENDING

    def test_finished_records_are_untouched(self):
        record = _record("x", status=ExecutionStatus.FAILED, error_message="boom")

        assert as_interrupted_if_orphaned(record, None) is record

    def test_meta_records_its_owner(self, tmp_path):
        store = FileLogStore(str(tmp_path))
        store.start_run(_record("r", status=ExecutionStatus.PENDING))

        owner = store.read_owner("r")

        assert owner and owner["pid"] == os.getpid()

    def test_listing_shows_a_file_only_pending_run_as_interrupted(self, tmp_path):
        store = FileLogStore(str(tmp_path))
        store.finish_run(_record("old", status=ExecutionStatus.PENDING))
        # Written by a process that is gone.
        meta = tmp_path / "old" / "meta.json"
        data = json.loads(meta.read_text())
        data["owner"] = {"pid": 2**22 + 54321, "host": data["owner"]["host"]}
        meta.write_text(json.dumps(data))

        [run] = _manager([], store).list_executions()

        assert run.status == ExecutionStatus.INTERRUPTED

    def test_a_run_this_process_holds_is_never_interrupted(self, tmp_path):
        store = FileLogStore(str(tmp_path))
        live = _record("live", status=ExecutionStatus.RUNNING)
        store.start_run(live)

        [run] = _manager([live], store).list_executions()

        assert run.status == ExecutionStatus.RUNNING

    def test_startup_persists_the_interruption(self, tmp_path):
        store = FileLogStore(str(tmp_path))
        store.finish_run(_record("old", status=ExecutionStatus.RUNNING))
        meta = tmp_path / "old" / "meta.json"
        data = json.loads(meta.read_text())
        data.pop("owner")
        meta.write_text(json.dumps(data))
        mgr = _manager([], store)

        mgr._settle_orphaned_runs()

        assert json.loads(meta.read_text())["status"] == "interrupted"

    def test_opening_an_orphaned_run_by_id(self, tmp_path):
        store = FileLogStore(str(tmp_path))
        store.finish_run(_record("old", status=ExecutionStatus.PENDING))
        meta = tmp_path / "old" / "meta.json"
        data = json.loads(meta.read_text())
        data.pop("owner")
        meta.write_text(json.dumps(data))

        record = asyncio.run(_manager([], store)._load_persisted_record("old"))

        assert record is not None and record.status == ExecutionStatus.INTERRUPTED


class TestJournalStatus:
    def _status(self, pipeline_status):
        return StreamingStatusResponse(
            execution_id="e",
            active=False,
            pipelines=[StreamingPipelineStatus(stream_execution_id="s", status=pipeline_status)],
        )

    def test_a_finished_run_whose_journal_says_running_is_interrupted(self):
        from ducta_server.services.streaming_status import settle_interrupted

        settled = settle_interrupted(self._status("running"), run_finished=True)

        assert settled.pipelines[0].status == "interrupted"

    def test_a_run_still_going_is_left_alone(self):
        from ducta_server.services.streaming_status import settle_interrupted

        settled = settle_interrupted(self._status("running"), run_finished=False)

        assert settled.pipelines[0].status == "running"

    def test_a_journal_that_recorded_its_end_is_left_alone(self):
        from ducta_server.services.streaming_status import settle_interrupted

        settled = settle_interrupted(self._status("stopped"), run_finished=True)

        assert settled.pipelines[0].status == "stopped"


class TestAuthOff:
    def _auth_svc(self):
        from ducta_server.auth.service import get_auth_service

        return get_auth_service()

    def test_refresh_gives_the_dev_admin_a_session(self):
        from ducta_server.routes.auth import RefreshRequest, refresh_token

        response = SimpleNamespace(
            set_cookie=lambda **_k: pytest.fail("no cookie when auth is off")
        )
        token = asyncio.run(
            refresh_token(
                RefreshRequest(),
                SimpleNamespace(headers={}, cookies={}),
                response,
                self._auth_svc(),
                store=None,
                settings=SimpleNamespace(auth_enabled=False),
            )
        )

        assert token.user.id == "dev-admin"
        assert token.access_token

    def test_refresh_still_needs_a_session_when_auth_is_on(self):
        from fastapi import HTTPException

        from ducta_server.routes.auth import RefreshRequest, refresh_token

        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                refresh_token(
                    RefreshRequest(),
                    SimpleNamespace(headers={}, cookies={}),
                    SimpleNamespace(),
                    self._auth_svc(),
                    store=None,
                    settings=SimpleNamespace(auth_enabled=True),
                )
            )
        assert exc.value.status_code == 401

    @pytest.mark.parametrize("enabled", [True, False])
    def test_auth_config_says_whether_credentials_are_asked(self, enabled):
        from ducta_server.routes.auth import get_auth_config

        config = asyncio.run(get_auth_config(SimpleNamespace(auth_enabled=enabled)))

        assert config.auth_enabled is enabled
