"""Regressions for the 2026-11-12 review of ducta.ai (Sentinel, child runs).

Each test failed on the code before the fix (see the review's reproduction scripts).
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from ducta.ai.agents.runs import ducta_command
from ducta.ai.agents.sentinel import actions
from ducta.ai.agents.sentinel.engine import Sentinel
from ducta.ai.agents.sentinel.incidents import Incident, Incidents
from ducta.ai.agents.sentinel.triage import RunEvent, event_from_certificate
from ducta.api.services import run_certificates

SALES = (
    Path(__file__).parents[3]
    / "src"
    / "ducta"
    / "skills"
    / "ducta"
    / "assets"
    / "examples"
    / "sales"
)
POLICY = "\nsentinel:\n  enabled: true\n  environments: [dev]\n"


class NoRuns:
    def rerun(self, *a: Any) -> None:
        return None


@pytest.fixture
def certs(monkeypatch) -> List[tuple]:
    found: List[tuple] = []
    monkeypatch.setattr(
        run_certificates,
        "certificates",
        lambda root, env: iter([(e, c) for e, c in found if env is None or e == env]),
    )
    return found


@pytest.fixture
def sales(tmp_path, certs) -> Path:
    root = tmp_path / "sales"
    shutil.copytree(SALES, root)
    (root / "ducta.yaml").write_text((root / "ducta.yaml").read_text() + POLICY)
    return root


def _cert(i: int, duration: float, pipeline: str = "bronze.sales", **kw: Any) -> Dict[str, Any]:
    return {
        "run_id": f"r{i}",
        "pipeline": pipeline,
        "status": "success",
        "started_at": f"2026-11-12T10:{i:02d}:00+00:00",
        "ended_at": f"2026-11-12T10:{i:02d}:30+00:00",
        "duration_seconds": duration,
        "nodes": [],
        **kw,
    }


# ---------------------------------------------------------------------------
# 1. A server-side re-run is handed to the event loop; off it, nothing is recorded
# ---------------------------------------------------------------------------


class TestServerReruns:
    def test_execute_off_the_event_loop_records_nothing(self, tmp_path):
        from ducta.api.execution.manager import ExecutionManager

        manager = ExecutionManager()
        with pytest.raises(RuntimeError):
            manager.execute(source_path=tmp_path, pipeline_name="p", env="dev")
        assert manager._store.list_all() == []
        assert manager._execution_queue.queue_depth == 0

    def test_execute_from_thread_without_a_running_manager_is_refused(self, tmp_path):
        from ducta.api.execution.manager import ExecutionManager

        manager = ExecutionManager()
        with pytest.raises(RuntimeError, match="not running"):
            manager.execute_from_thread(source_path=tmp_path, pipeline_name="p", env="dev")
        assert manager._store.list_all() == []

    def test_a_sentinel_rerun_from_a_worker_thread_runs_on_the_loop(self, tmp_path, monkeypatch):
        from ducta.api.execution.manager import ExecutionManager

        manager = ExecutionManager()
        seen: Dict[str, Any] = {}

        def fake_execute(**kwargs: Any) -> str:
            seen["loop"] = asyncio.get_running_loop()
            seen["thread"] = threading.current_thread()
            seen["kwargs"] = kwargs
            return "record"

        monkeypatch.setattr(manager, "execute", fake_execute)

        async def main() -> None:
            manager._loop = asyncio.get_running_loop()
            executor = actions.ServerExecutor(manager, "proj")
            # The way the hook, the periodic pass and Retry call it.
            await asyncio.to_thread(executor.rerun, tmp_path, "dev", "orders", ["clean"], True)
            assert seen["loop"] is manager._loop
            assert seen["thread"] is threading.main_thread()

        asyncio.run(main())
        assert seen["kwargs"]["user_id"] == "sentinel"
        assert seen["kwargs"]["node_names"] == ["clean"]


# ---------------------------------------------------------------------------
# 2. A child run does not put the project in front of the standard library
# ---------------------------------------------------------------------------


def test_a_project_module_does_not_shadow_the_standard_library(tmp_path):
    marker = tmp_path / "PLANTED"
    (tmp_path / "json.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    command = ducta_command("--help")
    assert command[1] == "-P"
    subprocess.run(command, cwd=tmp_path, capture_output=True, timeout=120)
    assert not marker.exists()


# ---------------------------------------------------------------------------
# 3. A slow run is found whether the server's hook or a scan saw it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("via_hook", [False, True])
def test_a_slow_run_opens_an_incident_however_it_was_seen(sales, certs, via_hook):
    certs += [("dev", _cert(i, 10.0)) for i in range(1, 7)]
    sentinel = Sentinel(sales, NoRuns(), notify=False)
    sentinel.run_once(["dev"])  # the first look takes history as seen
    slow = _cert(7, 100.0)
    certs.append(("dev", slow))
    if via_hook:
        sentinel.on_run_finished(event_from_certificate("dev", slow))
    sentinel.run_once(["dev"])
    assert [i.kind for i in Incidents(sales).list()] == ["slow"]


def test_a_slow_run_from_the_server_record_is_found(sales, certs):
    """The hook's event has a duration but no certificate."""
    certs += [("dev", _cert(i, 10.0)) for i in range(1, 7)]
    sentinel = Sentinel(sales, NoRuns(), notify=False)
    sentinel.run_once(["dev"])
    event = RunEvent(
        env="dev", pipeline="bronze.sales", status="success", run_id="srv-1", duration_seconds=90
    )
    sentinel.on_run_finished(event)
    assert [i.kind for i in Incidents(sales).list()] == ["slow"]


def test_a_late_pipeline_opens_an_sla_incident(sales, certs):
    pipeline = sales / "pipelines" / "bronze.sales.yaml"
    pipeline.write_text(
        pipeline.read_text().replace(
            "requires_dates: false\n", "requires_dates: false\nmetadata: {sla: 1h}\n", 1
        )
    )
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    certs.append(("dev", _cert(1, 10.0, started_at=old, ended_at=old)))
    Sentinel(sales, NoRuns(), notify=False).run_once(["dev"])
    assert [i.kind for i in Incidents(sales).list()] == ["sla_miss"]


def test_stale_nodes_open_a_stale_incident(sales, certs, monkeypatch):
    (sales / "ducta.yaml").write_text((sales / "ducta.yaml").read_text() + "  rerun_stale: true\n")
    monkeypatch.setattr(
        "ducta.api.services.staleness.node_freshness",
        lambda store, latest: {
            "land_orders": SimpleNamespace(
                state="stale", pipeline="bronze.sales", node="land_orders"
            )
        },
    )
    monkeypatch.setattr(
        "ducta.api.services.run_certificates.latest_successful", lambda root, env: {}
    )
    Sentinel(sales, NoRuns(), notify=False).run_once(["dev"])
    (incident,) = Incidents(sales).list()
    assert incident.kind == "stale"


# ---------------------------------------------------------------------------
# 4. The CLI re-run's outcome is its own certificate
# ---------------------------------------------------------------------------


class TestCertificateOfTheRerun:
    START = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
    END = datetime(2026, 11, 12, 10, 5, tzinfo=timezone.utc)

    def _at(self, minutes: float) -> str:
        return (self.START + timedelta(minutes=minutes)).isoformat()

    def test_a_later_run_by_a_person_is_not_taken(self, certs, tmp_path):
        certs += [
            ("dev", {"run_id": "sentinel", "pipeline": "p", "started_at": self._at(1)}),
            ("dev", {"run_id": "person", "pipeline": "p", "started_at": self._at(6)}),
            ("dev", {"run_id": "older", "pipeline": "p", "started_at": self._at(-10)}),
        ]
        found = actions._certificate_of_run(tmp_path, "dev", "p", self.START, self.END)
        assert found["run_id"] == "sentinel"

    def test_a_locked_rerun_takes_no_certificate(self, certs, tmp_path, monkeypatch):
        now = datetime.now(timezone.utc).isoformat()
        certs.append(("dev", {"run_id": "holder", "pipeline": "p", "started_at": now}))
        monkeypatch.setattr(
            "ducta.ai.agents.runs.run_pipeline",
            lambda *a, **k: SimpleNamespace(exit_code=7, output="locked", ok=False, locked=True),
        )
        event = actions.CliExecutor()._run(tmp_path, "dev", "p", [], False)
        assert event.run_id is None and event.status == "failed"


# ---------------------------------------------------------------------------
# 5. Old closed incidents leave the folder every pass reads
# ---------------------------------------------------------------------------


def test_old_closed_incidents_are_archived_and_still_readable(tmp_path):
    incidents = Incidents(tmp_path)
    long_ago = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    old = Incident(id="20260101-000000-aaaaaa", env="dev", pipeline="p", kind="failure")
    old.status, old.resolved_at, old.updated_at = "resolved", long_ago, long_ago
    recent = Incident(id="20261110-000000-bbbbbb", env="dev", pipeline="p", kind="failure")
    recent.status, recent.updated_at = "resolved", datetime.now(timezone.utc).isoformat()
    active = Incident(id="20260102-000000-cccccc", env="dev", pipeline="p", kind="failure")
    active.updated_at = long_ago
    for incident in (old, recent, active):
        incidents.save(incident)

    assert incidents.archive_closed() == [old.id]
    assert {i.id for i in incidents.list()} == {recent.id, active.id}
    assert incidents.get(old.id).status == "resolved"
