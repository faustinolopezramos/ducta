"""Unit tests for ducta.stream.exceptions helpers."""

from __future__ import annotations

import pytest

from ducta.stream.exceptions import (
    StreamingError,
    create_error_context,
    handle_streaming_error,
)


class TestCreateErrorContext:
    def test_basic_fields(self):
        ctx = create_error_context("start_pipeline", component="Manager", pipeline="p1")
        assert ctx["operation"] == "start_pipeline"
        assert ctx["component"] == "Manager"
        assert ctx["pipeline"] == "p1"
        assert "timestamp" in ctx

    def test_component_optional(self):
        ctx = create_error_context("op")
        assert "component" not in ctx


class TestHandleStreamingError:
    def test_passes_through_return_value(self):
        @handle_streaming_error
        def f(x):
            return x * 2

        assert f(21) == 42

    def test_wraps_unexpected_error(self):
        @handle_streaming_error
        def f():
            raise ValueError("boom")

        with pytest.raises(StreamingError, match="Unexpected error"):
            f()

    def test_streaming_error_passes_through(self):
        @handle_streaming_error
        def f():
            raise StreamingError("already typed")

        with pytest.raises(StreamingError, match="already typed"):
            f()
