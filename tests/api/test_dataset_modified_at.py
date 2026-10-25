"""When a dataset was last written, as the preview shows it."""

from __future__ import annotations

import os
from datetime import datetime

from ducta.api.services.dataset_preview import _modified_at


def _touch(path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    os.utime(path, (mtime, mtime))


def test_a_delta_table_is_dated_by_its_newest_commit(tmp_path):
    table = tmp_path / "orders"
    _touch(table / "_delta_log" / "00000000000000000000.json", 1_000)
    _touch(table / "_delta_log" / "00000000000000000001.json", 2_000)
    _touch(table / "part-0000.parquet", 9_000)  # data files are not read
    assert datetime.fromisoformat(_modified_at(table)).timestamp() == 2_000


def test_a_plain_directory_is_dated_by_its_newest_file(tmp_path):
    folder = tmp_path / "events"
    _touch(folder / "a.parquet", 1_000)
    _touch(folder / "day=1" / "b.parquet", 3_000)
    assert datetime.fromisoformat(_modified_at(folder)).timestamp() == 3_000


def test_a_file_an_empty_directory_and_a_missing_path(tmp_path):
    _touch(tmp_path / "x.csv", 5_000)
    assert datetime.fromisoformat(_modified_at(tmp_path / "x.csv")).timestamp() == 5_000
    (tmp_path / "empty").mkdir()
    assert _modified_at(tmp_path / "empty") is None
    assert _modified_at(tmp_path / "missing") is None
