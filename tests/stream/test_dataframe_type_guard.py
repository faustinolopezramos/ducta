"""Regression: `isinstance(x, DataFrame)` crashed when pyspark was absent.

``query_manager`` falls back to ``DataFrame = Any`` when pyspark cannot be
imported. That is fine for a type *annotation*, but the same name was also used
as an ``isinstance`` target — and ``typing.Any`` cannot be used with isinstance:
it raises ``TypeError: typing.Any cannot be used with isinstance()``.

The TypeError was then caught by the outer handler in ``_apply_transformations``
and re-raised as a generic ``TRANSFORMATION_FAILURE``, so a perfectly valid
transformation was reported as a transformation failure — and, worse, the test
covering the *invalid* return type passed for the wrong reason: it asserted only
that some StreamingError was raised, which the TypeError happened to produce.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from ducta.stream import query_manager as qm


@pytest.fixture
def no_spark_types(monkeypatch):
    """Force the structural fallback that runs when pyspark is unavailable.

    Several tests below describe MagicMocks shaped like a streaming DataFrame,
    which only `looks_like_dataframe`'s `hasattr` branch accepts. With pyspark
    installed the `isinstance` branch runs instead and rejects them, so without
    this the tests asserted the fallback's behaviour but only ever exercised it
    on machines where the extra was missing.
    """
    monkeypatch.setattr(qm, "SPARK_TYPES_AVAILABLE", False)


class TestTheHazardIsReal:
    def test_typing_any_cannot_be_used_with_isinstance(self):
        # The language behaviour the production code tripped over.
        with pytest.raises(TypeError, match="cannot be used with isinstance"):
            isinstance(object(), Any)


class TestLooksLikeDataFrame:
    def test_none_is_rejected(self):
        # A transform that forgets to return is the most common mistake.
        assert qm.looks_like_dataframe(None) is False

    @pytest.mark.parametrize("value", ["not-a-dataframe", 42, [], {}, object()])
    def test_plain_objects_are_rejected(self, value):
        assert qm.looks_like_dataframe(value) is False

    def test_it_never_raises_regardless_of_input(self):
        # The whole point: no input may produce a TypeError from the type system.
        for value in (None, "x", 0, [], {}, object(), MagicMock()):
            qm.looks_like_dataframe(value)

    def test_a_streaming_dataframe_shape_is_accepted(self, no_spark_types):
        streaming_df = MagicMock()
        streaming_df.writeStream = MagicMock()

        assert qm.looks_like_dataframe(streaming_df) is True

    def test_the_schema_plus_isstreaming_shape_is_accepted(self, no_spark_types):
        df = MagicMock(spec=["schema", "isStreaming"])

        assert qm.looks_like_dataframe(df) is True

    @pytest.mark.skipif(not qm.SPARK_TYPES_AVAILABLE, reason="requires a real pyspark install")
    def test_it_uses_a_real_isinstance_when_pyspark_is_present(self):
        from pyspark.sql import DataFrame

        assert qm.looks_like_dataframe(MagicMock(spec=DataFrame)) is True

    def test_the_availability_flag_matches_the_bound_name(self):
        # If the flag ever disagrees with what was actually imported, the
        # isinstance branch would be taken against `typing.Any` again.
        if qm.SPARK_TYPES_AVAILABLE:
            assert isinstance(qm.DataFrame, type)
        else:
            assert qm.DataFrame is Any


class TestReturnTypeValidationIsMeaningful:
    """The invalid-return-type path must fail *because the type is wrong*."""

    def test_a_wrong_return_type_is_reported_as_invalid_return_type(self, monkeypatch):
        from ducta.stream.exceptions import StreamingError

        manager = qm.StreamingQueryManager.__new__(qm.StreamingQueryManager)
        monkeypatch.setattr(
            manager, "_get_transform_function", lambda cfg: lambda df: "nope", raising=False
        )
        monkeypatch.setattr(
            manager, "_call_transform_function", lambda fn, df, params: fn(df), raising=False
        )

        with pytest.raises(StreamingError) as caught:
            manager._apply_transformations(MagicMock(), {"function": {"key": "bad"}})

        # Previously this surfaced as TRANSFORMATION_FAILURE (the swallowed
        # TypeError), which told the user nothing about their return type.
        assert caught.value.error_code == "INVALID_RETURN_TYPE"

    def test_a_valid_dataframe_passes_through_untouched(self, monkeypatch, no_spark_types):
        transformed = MagicMock()
        transformed.writeStream = MagicMock()

        manager = qm.StreamingQueryManager.__new__(qm.StreamingQueryManager)
        monkeypatch.setattr(
            manager, "_get_transform_function", lambda cfg: lambda df: transformed, raising=False
        )
        monkeypatch.setattr(
            manager, "_call_transform_function", lambda fn, df, params: fn(df), raising=False
        )

        result = manager._apply_transformations(MagicMock(), {"function": {"key": "ok"}})

        assert result is transformed

    def test_no_function_configured_returns_the_input_unchanged(self):
        manager = qm.StreamingQueryManager.__new__(qm.StreamingQueryManager)
        input_df = MagicMock()

        assert manager._apply_transformations(input_df, {}) is input_df
