"""Regression test: a bug inside the preflight validator itself must be
logged at a visible level (warning), not `debug` (typically suppressed in
production) — the fail-open behavior itself (continue without preflight) is
intentional and unchanged.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ducta.core.executors.facade import PipelineExecutor
from ducta.core.settings import CoreSettings


def _executor() -> PipelineExecutor:
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.context = MagicMock()
    executor.context.global_config = {"preflight_enabled": True}
    # __new__ bypasses __init__; settings are resolved once at construction.
    executor.settings = CoreSettings.from_context(executor.context)
    return executor


class TestPreflightValidatorCrashIsLoggedVisibly:
    def test_validator_exception_logs_a_warning(self):
        executor = _executor()
        with patch(
            "ducta.core.preflight.validate_pipeline",
            side_effect=RuntimeError("validator bug"),
        ):
            with patch("ducta.core.executors.facade.logger") as mock_logger:
                executor._run_preflight("pipeline1")  # must not raise (fail-open)
                mock_logger.warning.assert_called_once()
                mock_logger.debug.assert_not_called()
