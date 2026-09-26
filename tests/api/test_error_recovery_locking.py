"""Regression: `_error_logs` (module-level dict) had no lock, unlike its
sibling registry pattern (see `_registry.KeyedRegistry`) — multiple
concurrent pipeline executions (each in its own thread) calling
get_error_log/flush_error_log for their own execution_id could race on the
same dict.
"""

from __future__ import annotations

import threading

from ducta.api.execution import error_recovery


class TestErrorLogsLocking:
    def test_concurrent_get_error_log_creates_exactly_one_log_per_id(self):
        error_recovery._error_logs.clear()
        n_threads = 50
        barrier = threading.Barrier(n_threads)
        results = []
        results_lock = threading.Lock()

        def _get():
            barrier.wait()
            log = error_recovery.get_error_log("exec-1")
            with results_lock:
                results.append(log)

        threads = [threading.Thread(target=_get) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(id(r) for r in results)) == 1
        assert len(error_recovery._error_logs) == 1

    def test_flush_error_log_removes_from_registry(self):
        error_recovery._error_logs.clear()
        error_recovery.get_error_log("exec-2")
        assert "exec-2" in error_recovery._error_logs

        error_recovery._error_logs["exec-2"].save = lambda: None  # no disk I/O
        assert error_recovery.flush_error_log("exec-2") is True
        assert "exec-2" not in error_recovery._error_logs

    def test_flush_error_log_missing_returns_false(self):
        error_recovery._error_logs.clear()
        assert error_recovery.flush_error_log("does-not-exist") is False
