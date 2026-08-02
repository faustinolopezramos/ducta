"""Unit tests for ducta.mlrun.error_analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ducta.mlrun.error_analysis import segment_metrics, worst_records


class TestAlignmentByLabel:
    def test_perfect_predictor_scores_1_0_even_when_reordered(self):
        # y_pred is a perfect predictor of y_true, but computed on a
        # differently-ordered copy of the same rows (same index labels,
        # different row order) — a very plausible real pipeline shape.
        y_true = pd.Series([0, 1, 0, 1, 1], index=[10, 20, 30, 40, 50])
        y_pred = y_true.copy().sample(frac=1, random_state=0)  # same values, shuffled order
        assert not y_pred.index.equals(y_true.index)

        result = segment_metrics(
            y_true, y_pred, segments=pd.Series(["a"] * 5, index=y_true.index), min_rows=1
        )
        assert result["overall"]["accuracy"] == 1.0

    def test_worst_records_aligns_by_label_too(self):
        y_true = pd.Series([0, 1, 0, 1], index=[10, 20, 30, 40])
        y_pred = y_true.copy().sample(frac=1, random_state=1)
        out = worst_records(y_true, y_pred, task="classification")
        assert out.empty  # perfect predictor -> no misclassifications

    def test_mismatched_non_permutation_indices_raise(self):
        y_true = pd.Series([0, 1], index=[1, 2])
        y_pred = pd.Series([0, 1], index=[1, 3])  # not a permutation of y_true's index
        with pytest.raises(ValueError, match="not a permutation"):
            segment_metrics(y_true, y_pred, segments=pd.Series(["a", "a"], index=[1, 2]))

    def test_plain_arrays_still_align_positionally(self):
        # No index concept for plain lists/arrays — must keep working exactly
        # as before (positional).
        result = segment_metrics(
            [0, 1, 0, 1], [0, 1, 0, 1], segments=["a", "a", "a", "a"], min_rows=1
        )
        assert result["overall"]["accuracy"] == 1.0


class TestNaNSegmentsSurfaced:
    def test_nan_segment_rows_reported_in_skipped_not_dropped(self):
        y_true = pd.Series([1, 0, 1, 0, 1, 0])
        y_pred = pd.Series([0, 1, 1, 0, 1, 0])  # first two rows misclassified
        segments = pd.Series(["a", "a", None, None, "b", "b"])

        result = segment_metrics(y_true, y_pred, segments, min_rows=1)

        skipped_rows = sum(s["rows"] for s in result["skipped_segments"] if s["segment"] is None)
        assert skipped_rows == 2
        ranked_rows = sum(s["rows"] for s in result["segments"])
        assert ranked_rows == 4  # only "a" and "b" segments ranked, None excluded
