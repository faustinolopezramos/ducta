"""``-q`` on the classic log means "Errors only" (review 2026-11-11).

The banner, the quality and schema tables and the sections were printed straight
to the console whatever the log level: some 117 lines for a three-node run.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ducta.console.execution import _quiet_success_line
from ducta.console.ux.reporter import ConsoleReporter
from ducta.console.ux.rich_logger import RichLoggerManager
from ducta.core.results import PipelineRunResult


@pytest.fixture
def quiet_classic():
    RichLoggerManager.setup(quiet=True, file_logging=False)
    try:
        yield
    finally:
        RichLoggerManager.setup(file_logging=False)


def test_decoration_is_silenced_and_errors_are_not(quiet_classic):
    assert RichLoggerManager.get_console().quiet
    assert RichLoggerManager.get_error_console() is not RichLoggerManager.get_console()
    assert not RichLoggerManager.get_error_console().quiet


def test_passing_quality_reports_are_not_shown_failing_ones_are(quiet_classic):
    reporter = ConsoleReporter()
    assert reporter.quality_report(SimpleNamespace(passed=True)) is True  # handled: not shown
    assert reporter.quality_report(SimpleNamespace(passed=False)) is False  # engine prints it
    assert reporter.quality_summary([]) is True


def test_without_quiet_nothing_changes():
    RichLoggerManager.setup(file_logging=False)
    assert not RichLoggerManager.get_console().quiet
    assert RichLoggerManager.get_error_console() is RichLoggerManager.get_console()
    assert ConsoleReporter().quality_report(SimpleNamespace(passed=True)) is False


def test_quiet_success_line():
    result = PipelineRunResult(pipeline="etl")
    result.certificate_path = "data/dev/.ducta/runs/r1/certificate.json"
    line = _quiet_success_line("etl", result)
    assert line.startswith("✓ etl completed")
    assert line.endswith("certificate data/dev/.ducta/runs/r1/certificate.json")
