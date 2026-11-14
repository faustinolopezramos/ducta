"""The server's Sentinel hook: a run the server finished is triaged, and a re-run
is queued on the server's own execution manager, as the sentinel user."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai" / "agents"))
from conftest import no_real_model  # noqa: E402,F401
from test_sentinel import INFRA, certs, sales  # noqa: E402,F401

from ducta_server import sentinel_hooks  # noqa: E402


def test_the_server_hook_queues_a_rerun_as_sentinel(sales, monkeypatch):
    calls = []

    class Manager:
        def execute_from_thread(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("ducta_server.execution.manager.get_execution_manager", lambda: Manager())
    monkeypatch.setattr(
        "ducta_server.routes.execution.run_errors",
        lambda _id: [{"node_id": "land_orders", "message": INFRA}],
    )
    record = {
        "id": "e1",
        "pipeline_name": "bronze.sales",
        "env": "dev",
        "status": "failed",
        "error_message": INFRA,
    }
    sentinel_hooks.on_run_finished(sales, "sales", record)
    assert calls and calls[0]["user_id"] == "sentinel" and calls[0]["node_names"] == ["land_orders"]
