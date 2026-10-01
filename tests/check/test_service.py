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


class TestRunChecksOnAFile:
    """`ducta quality run --input FILE --config CHECKS`: a standalone checks file.

    It read the checks file through a format-1 console helper that was removed
    with that format, so every call failed with an ImportError.
    """

    @pytest.mark.parametrize(
        "name,body",
        [
            (
                "checks.yaml",
                "checks:\n  row_count: {min: 2}\n  null_rate: {columns: [id], threshold: 0}\n",
            ),
            ("checks.json", '{"checks": {"row_count": {"min": 2}}}'),
            ("checks.toml", "[checks.row_count]\nmin = 2\n"),
        ],
    )
    def test_runs_the_checks_in_the_file(self, tmp_path, name, body):
        data = tmp_path / "people.csv"
        data.write_text("id,name\n1,a\n2,b\n3,c\n")
        checks = tmp_path / name
        checks.write_text(body)

        report = QualityService.run_checks(
            input_path=str(data), format="csv", config_path=str(checks), workspace=str(tmp_path)
        )

        names = {r["check_name"] for r in report["results"]}
        assert "row_count" in names
        assert report["passed"] is True

    def test_a_python_checks_file_is_not_executed(self, tmp_path):
        data = tmp_path / "people.csv"
        data.write_text("id\n1\n")
        checks = tmp_path / "checks.py"
        checks.write_text("raise SystemExit('executed')\n")
        with pytest.raises(Exception) as exc:
            QualityService.run_checks(
                input_path=str(data), format="csv", config_path=str(checks), workspace=str(tmp_path)
            )
        assert "executed" not in str(exc.value)
