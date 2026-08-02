from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# ---------------------------------------------------------------------------
# Build a proper mock module hierarchy so that isinstance(…, SparkDataFrame),
# isinstance(…, pd.DataFrame), etc. all work, and unittest.mock.patch can
# traverse dotted paths like "pyspark.sql.SparkSession".
# ---------------------------------------------------------------------------

import types as _types


def _make_module(name: str, **attrs):
    """Create a module-like object with the given attributes."""
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

    PandasDataFrame = _types.new_class("PandasDataFrame", (object,), {})
    PolarsDataFrame = _types.new_class("PolarsDataFrame", (object,), {})

    StorageLevel = _types.new_class("StorageLevel", (object,), {})
    StorageLevel.MEMORY_AND_DISK = "MEMORY_AND_DISK"

    # --- module hierarchy ----------------------------------------------------
    ps_storagelevel = _make_module("pyspark.storagelevel", StorageLevel=StorageLevel)
    ps_functions = _make_module("pyspark.sql.functions")
    ps_types = _make_module("pyspark.sql.types")

    ps_connect_df = _make_module("pyspark.sql.connect.dataframe", DataFrame=ConnectDataFrame)
    ps_connect = _make_module("pyspark.sql.connect", dataframe=ps_connect_df)

    ps_session = _make_module("pyspark.sql.session", SparkSession=SparkSession)
    ps_sql = _make_module(
        "pyspark.sql",
        DataFrame=SparkDataFrame,
        SparkSession=SparkSession,
        session=ps_session,
        connect=ps_connect,
        types=ps_types,
        functions=ps_functions,
    )

    pyspark_mod = _make_module("pyspark", sql=ps_sql, storagelevel=ps_storagelevel)

    # --- third-party mocks ---------------------------------------------------
    pandas_mod = _make_module("pandas", DataFrame=PandasDataFrame)
    polars_mod = _make_module("polars", DataFrame=PolarsDataFrame)
    delta_mod = _make_module("delta")
    ducta_mlrun = _make_module("ducta.mlrun")
    ducta_mlrun_fp = _make_module("ducta.mlrun.fingerprint")

    # --- install into sys.modules -------------------------------------------
    mappings = {
        "pyspark": pyspark_mod,
        "pyspark.sql": ps_sql,
        "pyspark.sql.connect": ps_connect,
        "pyspark.sql.connect.dataframe": ps_connect_df,
        "pyspark.sql.session": ps_session,
        "pyspark.sql.types": ps_types,
        "pyspark.sql.functions": ps_functions,
        "pyspark.storagelevel": ps_storagelevel,
        "pandas": pandas_mod,
        "polars": polars_mod,
        "delta": delta_mod,
        "ducta.mlrun": ducta_mlrun,
        "ducta.mlrun.fingerprint": ducta_mlrun_fp,
    }
    for name, mod in mappings.items():
        if name not in sys.modules:
            sys.modules[name] = mod


_install_mocks()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def spark_session():
    spark = MagicMock()
    spark.conf.get.return_value = "false"
    spark.sparkContext._jvm = MagicMock()
    spark.sparkContext._jvm.java = MagicMock()
    spark.sparkContext.addJar = MagicMock()
    spark.sql = MagicMock()
    spark.createDataFrame = MagicMock()
    spark.read = MagicMock()
    spark.read.options.return_value = spark.read
    spark.read.format.return_value = spark.read
    spark.read.load.return_value = MagicMock()
    spark.read.jdbc = MagicMock()
    spark.read.option = MagicMock(return_value=spark.read)
    spark.read.load = MagicMock()

    spark._jvm = MagicMock()
    spark._jvm.com = MagicMock()
    spark._jvm.com.databricks = MagicMock()
    spark._jvm.com.databricks.spark = MagicMock()
    spark._jvm.com.databricks.spark.xml = MagicMock()

    return spark


@pytest.fixture
def spark_dataframe():
    df = MagicMock()
    df.isEmpty.return_value = False
    df.columns = ["col1", "col2", "col3"]
    df.schema = MagicMock()
    df.schema.names = ["col1", "col2", "col3"]
    df.write = MagicMock()
    df.write.format.return_value = df.write
    df.write.mode.return_value = df.write
    df.write.option.return_value = df.write
    df.write.partitionBy.return_value = df.write
    df.write.save = MagicMock()
    df.write.saveAsTable = MagicMock()
    df.persist = MagicMock()
    df.unpersist = MagicMock()
    df.rdd = MagicMock()
    df.filter = MagicMock(return_value=df)
    df.where = MagicMock(return_value=df)
    df.limit = MagicMock(return_value=df)
    df.collect = MagicMock(return_value=[])
    df.take = MagicMock(return_value=[])
    return df


@pytest.fixture
def spark_dataframe_spec():
    """Spark DataFrame mock with spec, for isinstance() checks."""
    from pyspark.sql import DataFrame as SparkDataFrame

    df = MagicMock(spec=SparkDataFrame)
    df.isEmpty.return_value = False
    return df


@pytest.fixture
def dict_context():
    return {
        "spark": None,
        "execution_mode": "local",
        "input_config": {},
        "output_config": {},
        "output_path": "/tmp/output",
        "global_settings": {
            "in_memory_handoff": False,
            "fill_none_on_error": False,
            "max_input_workers": 2,
            "enable_data_fingerprinting": False,
            "fingerprint_policy": "record",
        },
    }


@pytest.fixture
def dict_context_with_spark(dict_context, spark_session):
    dict_context["spark"] = spark_session
    return dict_context


class ObjectContext:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def obj_context():
    return ObjectContext(
        spark=None,
        execution_mode="local",
        input_config={},
        output_config={},
        output_path="/tmp/output",
        global_settings={
            "in_memory_handoff": False,
            "fill_none_on_error": False,
            "max_input_workers": 2,
            "enable_data_fingerprinting": False,
            "fingerprint_policy": "record",
        },
    )


@pytest.fixture
def obj_context_with_spark(obj_context, spark_session):
    obj_context.spark = spark_session
    return obj_context


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def mock_csv_file(temp_dir):
    p = temp_dir / "test.csv"
    p.write_text("col1,col2\n1,2\n3,4\n")
    return p


@pytest.fixture
def mock_parquet_dir(temp_dir):
    d = temp_dir / "test.parquet"
    d.mkdir()
    (d / "part-00000.parquet").write_text("fake")
    (d / "_SUCCESS").write_text("")
    return d


@pytest.fixture
def sample_node():
    return {
        "name": "test_node",
        "input": ["ds1", "ds2"],
        "output": ["schema.folder.table1"],
        "fail_fast": True,
    }


@pytest.fixture
def sample_input_config():
    return {
        "ds1": {"format": "csv", "filepath": "/tmp/ds1.csv"},
        "ds2": {"format": "parquet", "filepath": "/tmp/ds2.parquet"},
        "ds_query": {"format": "query", "query": "SELECT 1 AS col"},
    }
