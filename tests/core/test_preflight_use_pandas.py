"""`use_pandas` only changes how a pickle is read.

On a CSV or Parquet dataset it was accepted and ignored: the node still received a
Spark DataFrame, while the MLOps tutorial promised pandas. Preflight now says so,
and names the setting that does deliver pandas (`execution_mode: vectorized`).
"""

from __future__ import annotations

from ducta.core.preflight import PreflightReport, _check_use_pandas
from ducta.setting.schemas import InputFormat

NODE = {"input": {"training_data": "gold.churn.training_set"}}


def _warnings(entry):
    report = PreflightReport(pipeline_name="p")
    _check_use_pandas(report, "train", NODE, {"gold.churn.training_set": entry})
    return report.warnings


def test_use_pandas_on_parquet_is_reported():
    [warning] = _warnings({"format": InputFormat.PARQUET, "use_pandas": True})
    assert "execution_mode: vectorized" in warning and "parquet" in warning


def test_use_pandas_on_a_pickle_is_fine():
    assert _warnings({"format": "pickle", "use_pandas": True}) == []


def test_no_use_pandas_no_warning():
    assert _warnings({"format": InputFormat.CSV}) == []


def test_a_stream_node_input_spec_is_not_a_dataset():
    # A stream node's `input` is a source spec (a mapping): looking it up in the
    # catalog crashed `ducta config validate` with "unhashable type: 'dict'".
    report = PreflightReport(pipeline_name="p")
    stream = {"streaming": {"trigger": "5s"}, "input": {"format": "file_stream", "path": "x"}}
    _check_use_pandas(report, "ingest", stream, {})
    assert report.warnings == []
