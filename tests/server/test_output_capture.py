"""Regression: `ProcessOutputCapture._append_line` ANSI-stripped the line only
to classify its log level — the raw line (ANSI codes and all) was what
actually got persisted to logs.jsonl/returned by the API, leaking terminal
escape sequences into any consumer that isn't itself a terminal.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ducta_server.execution.output_capture import ProcessOutputCapture


class TestAppendLineStripsAnsi:
    def test_persisted_line_has_no_ansi_codes(self):
        manager = MagicMock()
        capture = ProcessOutputCapture.__new__(ProcessOutputCapture)
        capture.execution_id = "exec-1"
        capture.manager = manager

        capture._append_line("\x1b[1;92mSUCCESS\x1b[0m: node finished")

        manager._append_process_output.assert_called_once()
        _, args, kwargs = manager._append_process_output.mock_calls[0]
        persisted_line = args[1]
        assert "\x1b[" not in persisted_line
        assert persisted_line == "SUCCESS: node finished"


class TestServerTrafficStaysOutOfRunLogs:
    """The API server shares the process with a run: its access log and its
    request log were captured as the run's own output."""

    def _capture(self):
        capture = ProcessOutputCapture.__new__(ProcessOutputCapture)
        capture.execution_id = "exec-1"
        capture.manager = MagicMock()
        return capture

    def test_uvicorn_access_line_is_dropped(self):
        capture = self._capture()
        capture._append_line(
            'INFO:     127.0.0.1:52045 - "GET /api/projects/s/pipelines?source=%2FUsers%2Fx HTTP/1.1" 200 OK'
        )
        capture.manager._append_process_output.assert_not_called()

    def test_ordinary_info_line_is_kept(self):
        capture = self._capture()
        capture._append_line("INFO: wrote 120 rows to silver.orders")
        capture.manager._append_process_output.assert_called_once()

    def test_request_log_records_are_not_attributed_to_the_run(self):
        from ducta_server.execution.log_sink import make_log_filter

        manager = MagicMock()
        manager.get_buffer.return_value = object()
        keep = make_log_filter(get_active_id=lambda: "exec-1", log_manager=manager)
        assert (
            keep({"name": "ducta_server.middleware", "message": "-> GET /api/executions"}) is False
        )
        assert (
            keep({"name": "ducta_server.execution.manager", "message": "Executing shutdown step"})
            is True
        )


class TestQualityTableRowsLevel:
    """A green run showed "8 err" in the web UI: every passing check row has a
    Severity column that reads ERROR, and the level was found by keyword."""

    def test_passing_check_with_error_severity_is_not_an_error(self):
        from ducta_server.execution.output_capture import infer_process_output_level

        row = "│ empty_dataset │ ✓ PASS │ ERROR    │ Dataset has 508 rows              │"
        assert infer_process_output_level(row) == "INFO"

    def test_failing_check_takes_its_severity(self):
        from ducta_server.execution.output_capture import infer_process_output_level

        assert (
            infer_process_output_level("│ range │ ✗ FAIL │ ERROR │ 3 rows out of range │")
            == "ERROR"
        )
        assert infer_process_output_level("│ nulls │ ✗ FAIL │ WARN  │ 2% nulls │") == "WARNING"

    def test_plain_lines_keep_keyword_detection(self):
        from ducta_server.execution.output_capture import infer_process_output_level

        assert infer_process_output_level("Traceback (most recent call last):") == "ERROR"
        assert infer_process_output_level("26/11/18 WARN Utils: hostname") == "WARNING"
