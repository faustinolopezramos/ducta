"""Regression: `ProcessOutputCapture._append_line` ANSI-stripped the line only
to classify its log level — the raw line (ANSI codes and all) was what
actually got persisted to logs.jsonl/returned by the API, leaking terminal
escape sequences into any consumer that isn't itself a terminal.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ducta.api.execution.output_capture import ProcessOutputCapture


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
