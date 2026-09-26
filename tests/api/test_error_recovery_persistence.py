"""Persistence + load coverage for the categorized error log (WP1).

Covers: atomic save → load round-trip, load-after-flush (survives the
in-memory registry cleanup), empty-log no-op, and the retention prune.
"""

from __future__ import annotations

import json

import pytest

from ducta.api.execution import error_recovery
from ducta.api.execution.error_recovery import (
    ErrorAnalyzer,
    ErrorContext,
    ExecutionErrorLog,
    flush_error_log,
    get_error_log,
    load_error_log_summary,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path):
    """Point the disk persistence at a temp dir and reset the registry."""
    error_recovery._error_logs.clear()
    error_recovery._error_base_dir = lambda: str(tmp_path)
    yield
    error_recovery._error_logs.clear()


def _boom():
    raise ValueError("boom")


def _make_log(tmp_path, exec_id="exec-1", errors: int = 1, warnings: int = 1) -> ExecutionErrorLog:
    log = ExecutionErrorLog(exec_id, base_dir=str(tmp_path))
    for _ in range(errors):
        try:
            _boom()
        except Exception as exc:
            log.log_error(
                exc, ErrorContext(execution_id=exec_id, node_id="n1", node_type="task", attempt=1)
            )
    for _ in range(warnings):
        log.log_warning("disk full")
    return log


class TestSaveLoadRoundTrip:
    def test_save_writes_errors_json_atomically(self, tmp_path):
        log = _make_log(tmp_path, errors=2, warnings=1)
        log.save()

        payload = json.loads((tmp_path / "exec-1" / "errors.json").read_text(encoding="utf-8"))
        assert payload["execution_id"] == "exec-1"
        assert payload["error_count"] == 2
        assert payload["warning_count"] == 1
        assert payload["has_critical_errors"] is True  # ValueError → permanent
        assert not (tmp_path / "exec-1" / "errors.json.tmp").exists()

    def test_errors_carry_category_traceback_and_hint(self, tmp_path):
        log = _make_log(tmp_path)
        log.save()
        payload = json.loads((tmp_path / "exec-1" / "errors.json").read_text(encoding="utf-8"))

        entry = payload["errors"][0]
        assert entry["node_id"] == "n1"
        assert entry["error"]["type"] == "ValueError"
        assert entry["error"]["category"] == "permanent"
        assert "Traceback" in entry["error"]["traceback"]
        assert len(entry["error"]["traceback_lines"]) >= 1
        # Advice only — nothing retries a run, so no plan/strategy is recorded.
        assert "re-running unchanged will fail again" in entry["hint"]
        assert "recovery_plan" not in entry

    def test_empty_log_save_is_noop(self, tmp_path):
        log = get_error_log("exec-empty")
        log.save()
        assert not (tmp_path / "exec-empty").exists()

    def test_load_after_flush_survives_registry_cleanup(self, tmp_path):
        log = _make_log(tmp_path)
        log.save()
        flush_error_log("exec-1")

        summary = load_error_log_summary("exec-1")
        assert summary is not None
        assert summary["error_count"] == 1
        assert summary["errors"][0]["error"]["message"] == "boom"

    def test_load_returns_none_when_nothing_persisted(self, tmp_path):
        assert load_error_log_summary("never-ran") is None


class TestPruneRetention:
    def test_prune_keeps_only_most_recent_logs(self, tmp_path):
        for i in range(5):
            _make_log(tmp_path, exec_id=f"exec-{i}").save()
        for i in range(5):
            assert (tmp_path / f"exec-{i}" / "errors.json").is_file()

        error_recovery._prune_error_logs(max_keep=3)
        kept = [i for i in range(5) if (tmp_path / f"exec-{i}" / "errors.json").is_file()]
        assert kept == [2, 3, 4]


class TestLoadErrorLogSummary:
    def test_memory_wins_over_disk(self, tmp_path):
        log = _make_log(tmp_path, exec_id="exec-1")
        log.save()
        error_recovery._error_logs["exec-1"] = log
        log.log_warning("live update")

        summary = load_error_log_summary("exec-1")
        assert summary["warning_count"] == 2  # disk has 1, memory has 2
