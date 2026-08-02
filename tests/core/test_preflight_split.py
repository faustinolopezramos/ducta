"""Regression test: preflight must validate a pipeline's `split` config.

Before this, `validate_split_config` was defined in split_validator.py and
re-exported from `ducta.core`, but never called from `preflight.py` — a
misconfigured split (unknown method, missing stratify_col/time_col/group_col)
surfaced only deep inside `mlrun.split.split_dataframe` at execution time,
with zero preflight signal.
"""

from __future__ import annotations

from types import SimpleNamespace

from ducta.core.preflight import validate_pipeline


def _context(split_config):
    return SimpleNamespace(
        pipelines={
            "train_model": {
                "type": "ml",
                "nodes": ["train"],
                "requires_dates": False,
                "split": split_config,
            }
        },
        nodes_config={"train": {}},
        input_config={},
        output_config={},
    )


class TestPreflightValidatesSplitConfig:
    def test_unknown_split_method_is_reported_as_an_error(self):
        context = _context({"method": "temportal", "time_col": "ts", "test_size": 0.2})
        report = validate_pipeline(context, "train_model")
        assert any("split config" in e.lower() for e in report.errors)
        assert report.ok is False

    def test_stratified_missing_column_is_reported_as_an_error(self):
        context = _context({"method": "stratified", "test_size": 0.2})
        report = validate_pipeline(context, "train_model")
        assert any("stratify_col" in e for e in report.errors)

    def test_valid_split_config_adds_no_split_error(self):
        context = _context({"method": "temporal", "time_col": "ts", "test_size": 0.2})
        report = validate_pipeline(context, "train_model")
        assert not any("split config" in e.lower() for e in report.errors)

    def test_no_split_config_is_fine(self):
        context = _context(None)
        report = validate_pipeline(context, "train_model")
        assert not any("split config" in e.lower() for e in report.errors)
