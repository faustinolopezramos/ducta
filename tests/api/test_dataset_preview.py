"""Previewing a materialized dataset: parquet folders, csv, and honest refusals."""

from __future__ import annotations

import pytest

from ducta.api.services.dataset_preview import PreviewUnavailable, preview

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")


def test_a_parquet_folder_like_spark_writes(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_parquet(folder / "part-0.parquet")
    (folder / "_SUCCESS").write_text("")
    r = preview(str(folder), "parquet", limit=2)
    assert r["total_rows"] == 3
    assert [c["name"] for c in r["columns"]] == ["a", "b"]
    assert r["rows"] == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]


def test_csv(tmp_path):
    (tmp_path / "d.csv").write_text("a,b\n1,x\n2,y\n")
    assert preview(str(tmp_path / "d.csv"), "csv", 10)["rows"][1] == {"a": 2, "b": "y"}


@pytest.mark.parametrize(
    "path, fmt, why",
    [
        (None, "parquet", "no path"),
        ("s3://bucket/x", "parquet", "Remote"),
        ("/nowhere/at/all", "parquet", "Not materialized"),
        ("/tmp", "delta", "not previewed"),
    ],
)
def test_what_cannot_be_previewed_says_why(path, fmt, why):
    with pytest.raises(PreviewUnavailable, match=why):
        preview(path, fmt)
