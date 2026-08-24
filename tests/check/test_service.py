"""Unit tests for ducta.check.service.QualityService."""

from __future__ import annotations

import os
import time

import pytest

from ducta.check.service import QualityService
from ducta.check.storage import FileStorageBackend


class TestGetScore:
    def test_missing_workspace_gives_clear_message(self, tmp_path):
        """Regression: the "no quality data at all" guard must actually fire —
        it previously checked '.quality'.exists() *after* constructing
        FileStorageBackend, whose __init__ creates that very directory as a
        side effect, so the guard was dead code and users only ever saw the
        less specific "No quality reports found for run_id ..." message."""
        empty_workspace = tmp_path / "empty"
        empty_workspace.mkdir()

        with pytest.raises(FileNotFoundError, match="No quality data found"):
            QualityService.get_score("run1", workspace=str(empty_workspace))


def _age_report(storage: FileStorageBackend, dataset: str, run_id: str, seconds_ago: float) -> None:
    path = storage._reports_dir(dataset) / f"{run_id}.json"
    when = time.time() - seconds_ago
    os.utime(path, (when, when))


class TestGetReportPicksMostRecentByTime:
    """Regression: run_id is a random UUID fragment (str(uuid4())[:8]), not a
    sortable timestamp — get_report()/get_summary() must pick "latest" by
    file mtime, not by sorting run_id strings lexicographically."""

    def test_get_report_without_run_id_returns_the_most_recently_written_report(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        # "zzz99999" alphabetically follows "aaa11111", but is written and
        # aged *first* — the old sorted(run_ids)[-1] logic would pick it.
        storage.save_report({"score": 1, "run_id": "zzz99999"}, "zzz99999", "my_dataset")
        _age_report(storage, "my_dataset", "zzz99999", seconds_ago=100)
        storage.save_report({"score": 2, "run_id": "aaa11111"}, "aaa11111", "my_dataset")

        report = QualityService.get_report("my_dataset", storage=storage)

        assert report["run_id"] == "aaa11111"

    def test_get_summary_latest_run_id_is_the_most_recently_written_one(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        storage.save_report({"score": 1, "run_id": "zzz99999"}, "zzz99999", "my_dataset")
        _age_report(storage, "my_dataset", "zzz99999", seconds_ago=100)
        storage.save_report({"score": 2, "run_id": "aaa11111"}, "aaa11111", "my_dataset")

        summary = QualityService.get_summary(storage=storage)

        # pipeline_name omitted -> get_summary() qualifies as
        # "{pipeline_name}/{dataset_name}" (see QualityService.get_summary).
        entry = next(e for e in summary if e["dataset"].endswith("my_dataset"))
        assert entry["latest_run_id"] == "aaa11111"
        assert entry["latest_score"] == 2
        assert entry["run_count"] == 2
