"""Unit tests for ducta.console.validation helpers."""

from __future__ import annotations

import pytest

from ducta.console.core import ValidationError
from ducta.console.validation import (
    validate_conflicting_options,
    validate_date_iso,
    validate_enum_field,
    validate_json_string,
    validate_log_level,
    validate_positive_number,
    validate_required_field,
)


class TestEnumField:
    def test_valid(self):
        ok, err = validate_enum_field("sync", ["sync", "async"], "mode")
        assert ok is True and err is None

    def test_invalid_raises(self):
        with pytest.raises(ValidationError, match="Invalid mode"):
            validate_enum_field("bogus", ["sync", "async"], "mode")

    def test_invalid_non_raising(self):
        ok, err = validate_enum_field("bogus", ["sync"], "mode", raise_error=False)
        assert ok is False and "Invalid mode" in err


class TestJsonString:
    def test_none_is_ok(self):
        assert validate_json_string(None) == (True, None)

    def test_valid_json(self):
        assert validate_json_string('{"a": 1}') == (True, None)

    def test_invalid_json_raises(self):
        with pytest.raises(ValidationError, match="Invalid"):
            validate_json_string("{not json}")


class TestPositiveNumber:
    def test_positive_ok(self):
        assert validate_positive_number(10)[0] is True

    def test_zero_raises(self):
        with pytest.raises(ValidationError, match="must be positive"):
            validate_positive_number(0)

    def test_negative_raises(self):
        with pytest.raises(ValidationError, match="must be positive"):
            validate_positive_number(-5)

    def test_exceeds_max_warns_but_ok(self):
        ok, msg = validate_positive_number(200, max_val=100, field_name="port")
        assert ok is True
        assert "exceeds" in msg


class TestRequiredField:
    def test_present_ok(self):
        validate_required_field("value", "env")  # no raise

    def test_empty_raises(self):
        with pytest.raises(ValidationError, match="--env is required"):
            validate_required_field("", "env")


class TestDateIso:
    def test_valid(self):
        assert validate_date_iso("2026-01-01") is not None

    def test_none(self):
        assert validate_date_iso(None) is None

    def test_invalid_raises(self):
        with pytest.raises(ValidationError):
            validate_date_iso("not-a-date")


class TestConflictingOptions:
    def test_single_option_ok(self):
        assert validate_conflicting_options((True, "a"), (False, "b")) is True

    def test_multiple_raises(self):
        with pytest.raises(ValidationError):
            validate_conflicting_options((True, "a"), (True, "b"), raise_error=True)


class TestLogLevel:
    def test_valid(self):
        assert validate_log_level("INFO") is True

    def test_none_ok(self):
        assert validate_log_level(None) is True

    def test_invalid_raises(self):
        with pytest.raises(ValidationError):
            validate_log_level("VERBOSE")
