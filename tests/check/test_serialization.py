"""Unit tests for ducta.check.serialization: QualityReportSerializer / GateResultSerializer."""

from __future__ import annotations

from ducta.check.core import QualityReport
from ducta.check.serialization import QualityReportSerializer


class TestToParquetMetadata:
    def test_zero_score_is_not_na(self):
        """Regression: a real score of 0.0 (worst-quality dataset, the case an
        operator most needs to see) must not render as 'N/A' — the old
        ``if report.score else "N/A"`` treated 0.0 as falsy."""
        report = QualityReport(dataset_name="d", passed=False, score=0.0)
        meta = QualityReportSerializer.to_parquet_metadata(report)
        assert meta["score"] == "0.0"

    def test_nonzero_score_is_stringified(self):
        report = QualityReport(dataset_name="d", passed=True, score=0.87)
        meta = QualityReportSerializer.to_parquet_metadata(report)
        assert meta["score"] == "0.87"
