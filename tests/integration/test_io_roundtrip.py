"""What Ducta writes, Ducta reads back the same.

A pipeline's nodes talk to each other through these files, so a value changed on the way
through is silent corruption: the run succeeds and its certificate says so. Each format goes
through the real writer and the real reader with the awkward values CSV in particular got
wrong (a doubled quote, a phantom row from a line break, trimmed spaces).
"""

from __future__ import annotations

import pytest

from ducta.gate.readers import CSVReader, JSONReader, ORCReader, ParquetReader
from ducta.gate.writers import CSVWriter, JSONWriter, ORCWriter, ParquetWriter

pytest.importorskip("pyspark")

ROWS = [
    (1, 'has "quote"'),
    (2, "line1\nline2"),
    (3, "  spaces  "),
    (4, "a,b"),
    (5, "back\\slash"),
    (6, '\\"mixed\\"'),
    (7, "ñ € 漢字"),
    (8, "NULL"),
    (9, None),
    (10, ""),
]

FORMATS = {
    "parquet": (ParquetWriter, ParquetReader),
    "orc": (ORCWriter, ORCReader),
    "json": (JSONWriter, JSONReader),
    "csv": (CSVWriter, CSVReader),
}


def _round_trip(spark, tmp_path, fmt, rows=ROWS, write_options=None, read_options=None):
    writer_cls, reader_cls = FORMATS[fmt]
    context = {"spark": spark}
    path = str(tmp_path / fmt)
    df = spark.createDataFrame(rows, "id INT, txt STRING")
    writer_cls(context).write(df, path, {"options": write_options or {}})
    back = reader_cls(context).read(path, {"options": read_options or {}})
    return sorted(((int(r["id"]), r["txt"]) for r in back.collect()), key=lambda r: r[0])


@pytest.mark.parametrize("fmt", ["parquet", "orc", "json"])
def test_every_value_comes_back_the_same(spark, tmp_path, fmt):
    assert _round_trip(spark, tmp_path, fmt) == ROWS


def test_csv_keeps_quotes_line_breaks_spaces_and_the_row_count(spark, tmp_path):
    # An empty string reads back as null: a CSV has no way to tell them apart that Spark's
    # reader honours. The one difference, and docs/configuration.rst says so.
    expected = [(i, None if txt == "" else txt) for i, txt in ROWS]
    assert _round_trip(spark, tmp_path, "csv") == expected


def test_csv_options_of_the_dataset_win_over_the_defaults(spark, tmp_path):
    # `multiLine: false` is the documented way out for a large file: the phantom row is back,
    # which is what proves the default is doing the work.
    rows = _csv_rows_without_multiline(spark, tmp_path)
    assert len(rows) == 3


def _csv_rows_without_multiline(spark, tmp_path):
    path = str(tmp_path / "csv")
    df = spark.createDataFrame([(1, "line1\nline2"), (2, "x")], "id INT, txt STRING")
    CSVWriter({"spark": spark}).write(df, path, {"options": {}})
    reader = CSVReader({"spark": spark})
    return reader.read(path, {"options": {"multiLine": "false"}}).collect()


def test_spark_settings_do_not_cross_between_projects(spark):
    # The API server runs every project on one JVM session.
    from unittest.mock import patch

    from ducta.setting.session import SparkSessionManager as manager

    key = "spark.sql.sources.partitionOverwriteMode"
    manager._conf_owner, manager._owner_conf = None, {}
    with patch("ducta.setting.session.SparkSessionFactory.create_session", return_value=spark):
        try:
            spark.conf.set(key, "dynamic")  # what the first builder leaves on the session
            manager.get_or_create_session("local", {key: "dynamic"})
            manager.get_or_create_session("local", {})
            assert spark.conf.get(key) == "STATIC"
            manager.get_or_create_session("local", {key: "dynamic"})
            assert spark.conf.get(key) == "dynamic"
        finally:
            spark.conf.unset(key)
            manager._sessions.clear()  # not cleanup_all: it would stop the shared session
            manager._session_metadata.clear()
            manager._conf_owner, manager._owner_conf = None, {}
