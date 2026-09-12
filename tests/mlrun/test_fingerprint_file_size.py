"""A dataset's recorded size must be the dataset's size.

Every Spark-written dataset is a *directory* of ``part-`` files, and
``_capture_file_stat`` called ``os.stat`` on it — which returns the size of the
directory entry, not of its contents. On macOS that is 192 bytes, and it was 192
bytes in the run certificate whether the dataset held five rows or five million.

That field exists to describe what a run produced, so a number that never varies
with the content is worse than no number: it looks like evidence and is not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.mlrun.fingerprint import DataFingerprint


class TestTotalSizeBytes:
    def test_a_single_file_reports_its_own_size(self, tmp_path: Path):
        target = tmp_path / "data.csv"
        target.write_bytes(b"x" * 1234)

        assert DataFingerprint._total_size_bytes(str(target)) == 1234

    def test_a_directory_sums_its_part_files(self, tmp_path: Path):
        """The Spark layout: several part files plus a _SUCCESS marker."""
        target = tmp_path / "dataset"
        target.mkdir()
        (target / "part-00000.parquet").write_bytes(b"a" * 500)
        (target / "part-00001.parquet").write_bytes(b"b" * 700)
        (target / "_SUCCESS").write_bytes(b"")

        assert DataFingerprint._total_size_bytes(str(target)) == 1200

    def test_it_recurses_into_partitions(self, tmp_path: Path):
        """Partitioned output nests the part files one level down."""
        target = tmp_path / "dataset"
        (target / "dt=2024-01-01").mkdir(parents=True)
        (target / "dt=2024-01-02").mkdir(parents=True)
        (target / "dt=2024-01-01" / "part-0.parquet").write_bytes(b"a" * 100)
        (target / "dt=2024-01-02" / "part-0.parquet").write_bytes(b"b" * 250)

        assert DataFingerprint._total_size_bytes(str(target)) == 350

    def test_size_tracks_content(self, tmp_path: Path):
        """The property the old implementation could not have: it varies."""
        small = tmp_path / "small"
        small.mkdir()
        (small / "part-0.parquet").write_bytes(b"a" * 10)
        big = tmp_path / "big"
        big.mkdir()
        (big / "part-0.parquet").write_bytes(b"a" * 10_000)

        assert DataFingerprint._total_size_bytes(str(big)) > DataFingerprint._total_size_bytes(
            str(small)
        )

    def test_an_empty_directory_is_zero_not_the_dir_entry_size(self, tmp_path: Path):
        target = tmp_path / "empty"
        target.mkdir()

        assert DataFingerprint._total_size_bytes(str(target)) == 0

    def test_a_missing_path_is_none(self, tmp_path: Path):
        assert DataFingerprint._total_size_bytes(str(tmp_path / "nope")) is None
