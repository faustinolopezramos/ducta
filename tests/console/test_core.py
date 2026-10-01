"""Unit tests for ducta.console.core (dates, exit codes, errors)."""

from __future__ import annotations

import pytest

from ducta.console.core import (
    DuctaError,
    ExitCode,
    ValidationError,
    parse_iso_date,
    validate_date_range,
)


class TestParseIsoDate:
    def test_valid(self):
        assert parse_iso_date("2026-01-15") == "2026-01-15"

    def test_none(self):
        assert parse_iso_date(None) is None

    def test_invalid_raises(self):
        with pytest.raises(ValidationError, match="Invalid date format"):
            parse_iso_date("15-01-2026")


class TestValidateDateRange:
    def test_valid_range(self):
        validate_date_range("2026-01-01", "2026-01-31")  # no raise

    def test_start_after_end_raises(self):
        with pytest.raises(ValidationError, match="must be <="):
            validate_date_range("2026-02-01", "2026-01-01")

    def test_bad_format_raises(self):
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            validate_date_range("bad", "2026-01-01")

    def test_partial_dates_ok(self):
        # only one side provided -> no range check
        validate_date_range("2026-01-01", None)
        validate_date_range(None, None)


class TestExitCode:
    def test_success_zero(self):
        assert ExitCode.SUCCESS.value == 0

    def test_general_error_one(self):
        assert ExitCode.GENERAL_ERROR.value == 1


class TestDuctaError:
    # `exit_code` is the plain int the engine's base class declares, so that
    # `UnifiedCLI.run` can return it directly whether the error came from the
    # console or from `ducta.core`. The constructor still takes the enum.
    def test_default_exit_code(self):
        err = DuctaError("boom")
        assert err.exit_code == ExitCode.GENERAL_ERROR.value

    def test_validation_error_exit_code(self):
        assert ValidationError("x").exit_code == ExitCode.VALIDATION_ERROR.value

    def test_console_errors_are_engine_errors(self):
        # One `except` clause in the CLI has to cover both hierarchies.
        from ducta.core.errors import DuctaError as EngineError

        assert isinstance(ValidationError("x"), EngineError)
