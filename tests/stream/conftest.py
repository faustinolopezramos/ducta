from __future__ import annotations

import sys
import types as _types
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Duplicated (not shared) from tests/gate/conftest.py by design: each test
# subtree installs its own mock module hierarchy in sys.modules, guarded by
# ``if name not in sys.modules`` so whichever conftest runs first "wins" and
# later ones become no-ops (see tests/conftest.py for the same convention).
# ---------------------------------------------------------------------------


def _make_module(name: str, **attrs):
    mod = _types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _install_mocks():
    # --- type objects used for isinstance() checks ---------------------------
    SparkDataFrame = _types.new_class(
        "SparkDataFrame", (object,), exec_body=lambda ns: ns.update({"isEmpty": lambda self: False})
    )
    ConnectDataFrame = _types.new_class(
        "ConnectDataFrame",
        (object,),
        exec_body=lambda ns: ns.update({"isEmpty": lambda self: False}),
    )
    SparkSession = _types.new_class("SparkSession", (object,), {})
    SparkSession.getActiveSession = staticmethod(lambda: None)

    StreamingQuery = _types.new_class("StreamingQuery", (object,), {})
    DataStreamWriter = _types.new_class("DataStreamWriter", (object,), {})
    DataStreamReader = _types.new_class("DataStreamReader", (object,), {})

    StructType = _types.new_class("StructType", (object,), {})

    # --- module hierarchy ----------------------------------------------------
    ps_functions = _make_module("pyspark.sql.functions", col=MagicMock(), from_json=MagicMock())
    ps_types = _make_module("pyspark.sql.types", StructType=StructType)

    ps_connect_df = _make_module("pyspark.sql.connect.dataframe", DataFrame=ConnectDataFrame)
    ps_connect = _make_module("pyspark.sql.connect", dataframe=ps_connect_df)

    ps_streaming = _make_module(
        "pyspark.sql.streaming",
        StreamingQuery=StreamingQuery,
        DataStreamWriter=DataStreamWriter,
        DataStreamReader=DataStreamReader,
    )

    ps_session = _make_module("pyspark.sql.session", SparkSession=SparkSession)
    ps_sql = _make_module(
        "pyspark.sql",
        DataFrame=SparkDataFrame,
        SparkSession=SparkSession,
        session=ps_session,
        connect=ps_connect,
        types=ps_types,
        functions=ps_functions,
        streaming=ps_streaming,
    )

    pyspark_mod = _make_module("pyspark", sql=ps_sql)

    pandas_mod = _make_module(
        "pandas", DataFrame=_types.new_class("PandasDataFrame", (object,), {})
    )
    polars_mod = _make_module(
        "polars", DataFrame=_types.new_class("PolarsDataFrame", (object,), {})
    )
    delta_mod = _make_module("delta", tables=_make_module("delta.tables"))
    ducta_mlrun = _make_module("ducta.mlrun")
    ducta_mlrun_fp = _make_module("ducta.mlrun.fingerprint")

    mappings = {
        "pyspark": pyspark_mod,
        "pyspark.sql": ps_sql,
        "pyspark.sql.connect": ps_connect,
        "pyspark.sql.connect.dataframe": ps_connect_df,
        "pyspark.sql.session": ps_session,
        "pyspark.sql.types": ps_types,
        "pyspark.sql.functions": ps_functions,
        "pyspark.sql.streaming": ps_streaming,
        "pandas": pandas_mod,
        "polars": polars_mod,
        "delta": delta_mod,
        "delta.tables": delta_mod.tables,
        "ducta.mlrun": ducta_mlrun,
        "ducta.mlrun.fingerprint": ducta_mlrun_fp,
    }
    for name, mod in mappings.items():
        if name not in sys.modules:
            sys.modules[name] = mod
        elif name == "pyspark.sql" and not hasattr(sys.modules[name], "streaming"):
            # gate's conftest may have installed pyspark.sql first, without
            # the streaming submodule stream needs — attach it non-destructively.
            sys.modules[name].streaming = ps_streaming
            if "pyspark.sql.streaming" not in sys.modules:
                sys.modules["pyspark.sql.streaming"] = ps_streaming


_install_mocks()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_streaming_query():
    """A stand-in StreamingQuery whose active/stop/awaitTermination behave
    consistently, mirroring real Spark semantics closely enough for tests."""

    class _FakeStreamingQuery:
        def __init__(self, active=True, name="q", query_id="id-1", progress=None, exc=None):
            self._active = active
            self.name = name
            self.id = query_id
            self.runId = query_id
            self.lastProgress = progress
            self._exc = exc

        def isActive(self):  # noqa: N802 - mirrors Spark API
            return self._active

        def stop(self):
            self._active = False

        def awaitTermination(self, timeout=None):  # noqa: N802
            return not self._active

        def exception(self):
            return self._exc

    return _FakeStreamingQuery


@pytest.fixture
def spark_session():
    spark = MagicMock()
    spark.conf.get.return_value = "false"
    spark.version = "3.5.0"

    spark.readStream = MagicMock()
    spark.readStream.format.return_value = spark.readStream
    spark.readStream.options = MagicMock(return_value=spark.readStream)
    spark.readStream.option = MagicMock(return_value=spark.readStream)
    spark.readStream.schema = MagicMock(return_value=spark.readStream)
    spark.readStream.load = MagicMock(return_value=MagicMock())

    spark.streams = MagicMock()
    spark.streams.active = []
    spark.streams.addListener = MagicMock()
    spark.streams.removeListener = MagicMock()

    spark.sparkContext = MagicMock()
    spark.sparkContext.defaultParallelism = 4
    spark.sparkContext.setLocalProperty = MagicMock()

    return spark


@pytest.fixture
def streaming_dataframe(spark_session):
    """A mock streaming DataFrame recognized by isinstance(..., pyspark.sql.DataFrame)."""
    from pyspark.sql import DataFrame as SparkDataFrame

    df = MagicMock(spec=SparkDataFrame)
    df.columns = ["id", "event_time", "value"]
    df.dtypes = [("id", "int"), ("event_time", "timestamp"), ("value", "double")]
    df.sparkSession = spark_session

    df.writeStream = MagicMock()
    for method in ("outputMode", "queryName", "option", "trigger", "partitionBy", "format"):
        getattr(df.writeStream, method).return_value = df.writeStream

    df.select = MagicMock(return_value=df)
    df.withColumn = MagicMock(return_value=df)
    df.withWatermark = MagicMock(return_value=df)
    return df


@pytest.fixture
def dict_context(spark_session):
    return {
        "spark": spark_session,
        "execution_mode": "local",
        "output_path": "/tmp/output",
        "global_config": {
            "checkpoints_base": "/tmp/checkpoints",
            "max_streaming_pipelines": 5,
        },
    }


class ObjectContext:
    def __init__(self, **kwargs: Any):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def obj_context(spark_session):
    return ObjectContext(
        spark=spark_session,
        execution_mode="local",
        output_path="/tmp/output",
        env="test",
        format_policy=None,
        global_config={
            "checkpoints_base": "/tmp/checkpoints",
            "max_streaming_pipelines": 5,
        },
    )
