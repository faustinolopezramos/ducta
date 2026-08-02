"""Unit tests for ducta.core.split_validator."""

from __future__ import annotations

import pytest

from ducta.core.split_validator import (
    SplitValidationError,
    document_split_semantics,
    validate_split_config,
)


class TestValidateSplitConfig:
    def test_valid_random(self):
        # no raise
        validate_split_config({"method": "random", "test_size": 0.2}, dataset_size=1000)

    def test_test_size_out_of_range(self):
        with pytest.raises(SplitValidationError, match="test_size"):
            validate_split_config({"test_size": 1.5}, dataset_size=1000)

    def test_val_plus_test_too_large(self):
        with pytest.raises(SplitValidationError, match="val_size \\+ test_size"):
            validate_split_config({"test_size": 0.6, "val_size": 0.5}, dataset_size=1000)

    def test_stratified_requires_column(self):
        with pytest.raises(SplitValidationError, match="stratify_col"):
            validate_split_config({"method": "stratified", "test_size": 0.2}, 1000)

    def test_temporal_requires_time_col(self):
        with pytest.raises(SplitValidationError, match="time_col"):
            validate_split_config({"method": "temporal", "test_size": 0.2}, 1000)

    def test_group_requires_group_col(self):
        with pytest.raises(SplitValidationError, match="group_col"):
            validate_split_config({"method": "group", "test_size": 0.2}, 1000)

    def test_stratified_with_column_ok(self):
        validate_split_config(
            {"method": "stratified", "test_size": 0.2, "stratify_col": "label"}, 1000
        )

    def test_unknown_method_raises(self):
        # Previously fell through silently: none of the method-specific
        # branches (stratified/temporal/group) matched an unrecognized value,
        # and the config was accepted as if valid.
        with pytest.raises(SplitValidationError, match="Unknown split method"):
            validate_split_config({"method": "temportal", "test_size": 0.2}, 1000)


class TestDocumentSplitSemantics:
    def test_returns_readable_string(self):
        doc = document_split_semantics({"method": "temporal", "time_col": "ts", "test_size": 0.2})
        assert isinstance(doc, str)
        assert "temporal" in doc.lower()
