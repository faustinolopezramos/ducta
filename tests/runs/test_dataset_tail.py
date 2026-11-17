"""The newest rows of a sink that a stream is writing to: the live monitor's data."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd
import pytest

from ducta.runs.dataset_preview import MAX_CELL_CHARS, PreviewUnavailable, tail_rows


def _parquet(path: Path, rows: list[dict], *, age: float = 0.0, groups: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False, row_group_size=groups)
    when = time.time() - age
    os.utime(path, (when, when))
    return path


def test_parquet_newest_file_first_and_newest_row_first(tmp_path):
    out = tmp_path / "silver"
    _parquet(out / "part-0.parquet", [{"id": 1}, {"id": 2}], age=60)
    _parquet(out / "part-1.parquet", [{"id": 3}, {"id": 4}], age=10)
    result = tail_rows(str(out), "parquet", limit=3)
    assert [r["id"] for r in result["rows"]] == [4, 3, 2]
    assert result["total_rows"] == 4
    assert result["files"] == 2
    assert [c["name"] for c in result["columns"]] == ["id"]
    assert result["newest_at"]


def test_reads_the_last_row_groups_of_a_big_file(tmp_path):
    out = tmp_path / "bronze"
    _parquet(out / "part-0.parquet", [{"id": i} for i in range(100)], groups=10)
    assert [r["id"] for r in tail_rows(str(out), "parquet", limit=5)["rows"]] == [
        99,
        98,
        97,
        96,
        95,
    ]


def test_spark_bookkeeping_is_not_data(tmp_path):
    out = tmp_path / "delta"
    _parquet(out / "part-0.parquet", [{"id": 1}])
    _parquet(out / "_delta_log" / "00000.checkpoint.parquet", [{"action": "meta"}], age=-5)
    _parquet(out / "_spark_metadata" / "0.parquet", [{"x": 1}], age=-5)
    (out / ".part-0.parquet.crc").write_bytes(b"x")
    result = tail_rows(str(out), "delta", limit=10)
    assert [r["id"] for r in result["rows"]] == [1]
    assert result["files"] == 1


def test_partitioned_directories_are_read(tmp_path):
    out = tmp_path / "by_day"
    _parquet(out / "day=2026-11-15" / "part-0.parquet", [{"id": 1}], age=100)
    _parquet(out / "day=2026-11-16" / "part-0.parquet", [{"id": 2}], age=1)
    assert [r["id"] for r in tail_rows(str(out), "parquet", limit=5)["rows"]] == [2, 1]


def test_json_lines_newest_last_lines_first(tmp_path):
    out = tmp_path / "events"
    out.mkdir()
    old = out / "part-0.json"
    old.write_text("\n".join(json.dumps({"id": i}) for i in (1, 2)) + "\n")
    os.utime(old, (time.time() - 50, time.time() - 50))
    new = out / "part-1.json"
    new.write_text(
        "\n".join(json.dumps({"id": i}) for i in (3, 4)) + '\n{"id": 5, "cut'
    )  # a write in progress
    result = tail_rows(str(out), "json", limit=3)
    assert [r["id"] for r in result["rows"]] == [4, 3, 2]
    assert result["total_rows"] is None


def test_csv_keeps_its_header(tmp_path):
    out = tmp_path / "csv"
    out.mkdir()
    (out / "part-0.csv").write_text("id,name\n1,a\n2,b\n3,c\n")
    result = tail_rows(str(out), "csv", limit=2)
    assert result["rows"] == [{"id": 3, "name": "c"}, {"id": 2, "name": "b"}]
    assert [c["name"] for c in result["columns"]] == ["id", "name"]


def test_a_long_cell_is_cut(tmp_path):
    out = tmp_path / "docs"
    _parquet(out / "part-0.parquet", [{"body": "x" * 5000}])
    body = tail_rows(str(out), "parquet", limit=1)["rows"][0]["body"]
    assert len(body) == MAX_CELL_CHARS + 1 and body.endswith("…")


def test_a_half_written_parquet_file_is_skipped(tmp_path):
    out = tmp_path / "live"
    _parquet(out / "part-0.parquet", [{"id": 1}], age=30)
    (out / "part-1.parquet").write_bytes(b"PAR1 not a footer yet")
    assert [r["id"] for r in tail_rows(str(out), "parquet", limit=5)["rows"]] == [1]


@pytest.mark.parametrize(
    ("fmt", "why"),
    [("kafka", "kafka"), ("console", "console"), ("memory", "memory")],
)
def test_sinks_without_files_say_so(tmp_path, fmt, why):
    with pytest.raises(PreviewUnavailable, match=why):
        tail_rows(str(tmp_path), fmt)


def test_unavailable_reasons(tmp_path):
    with pytest.raises(PreviewUnavailable, match="Nothing written yet"):
        tail_rows(str(tmp_path / "nope"), "parquet")
    (tmp_path / "empty").mkdir()
    with pytest.raises(PreviewUnavailable, match="No data files"):
        tail_rows(str(tmp_path / "empty"), "parquet")
    with pytest.raises(PreviewUnavailable, match="Remote storage"):
        tail_rows("s3a://bucket/x", "parquet")
    with pytest.raises(PreviewUnavailable, match="no path"):
        tail_rows(None, "parquet")


# ── Re-reading a sink that is being polled: only what landed since costs anything ──


def test_an_unchanged_sink_is_answered_again_without_reading_rows(tmp_path, monkeypatch):
    from ducta.runs import dataset_preview

    out = tmp_path / "cached"
    _parquet(out / "part-0.parquet", [{"id": 1}, {"id": 2}], age=30)
    first = tail_rows(str(out), "parquet", limit=5)
    reads = []
    real = dataset_preview._tail_parquet
    monkeypatch.setattr(dataset_preview, "_tail_parquet", lambda *a: reads.append(1) or real(*a))
    again = tail_rows(str(out), "parquet", limit=5)
    assert again == first and reads == []

    _parquet(out / "part-1.parquet", [{"id": 3}], age=0)  # a batch lands
    after = tail_rows(str(out), "parquet", limit=5)
    assert reads == [1]
    assert [r["id"] for r in after["rows"]] == [3, 2, 1]
    assert after["total_rows"] == 3


def test_footers_are_counted_once_and_over_several_reads_past_the_budget(tmp_path, monkeypatch):
    from ducta.runs import dataset_preview

    monkeypatch.setattr(dataset_preview, "_FOOTER_BUDGET", 2)
    out = tmp_path / "many"
    for i in range(5):
        _parquet(out / f"part-{i}.parquet", [{"id": i}], age=50 - i)
    # Five footers, two per read: the total is not known until the third read.
    assert tail_rows(str(out), "parquet", limit=1)["total_rows"] is None
    assert tail_rows(str(out), "parquet", limit=1)["total_rows"] is None
    assert tail_rows(str(out), "parquet", limit=1)["total_rows"] == 5

    opened = []
    import pyarrow.parquet as pq

    real = pq.ParquetFile
    monkeypatch.setattr(pq, "ParquetFile", lambda p: opened.append(p) or real(p))
    _parquet(out / "part-5.parquet", [{"id": 5}], age=0)
    result = tail_rows(str(out), "parquet", limit=1)
    assert result["total_rows"] == 6
    # Only the new file's footer is opened to count (the rows read it once more).
    assert [Path(p).name for p in opened].count("part-5.parquet") >= 1
    assert all(Path(p).name == "part-5.parquet" for p in opened)
