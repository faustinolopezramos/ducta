from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import types as _types


def _make_module(name: str, **attrs):
    mod = _types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _install_mocks():
    # ------------------------------------------------------------------ #
    # pydantic mock — supports BaseModel, Field, validators, model_dump  #
    # ------------------------------------------------------------------ #
    class _PydanticBaseModel:
        def __init__(self, **kwargs):
            self._values = {}
            for k, v in kwargs.items():
                setattr(self, k, v)
                self._values[k] = v

        def model_dump(self, **kw):
            result = {}
            for k, v in self._values.items():
                if isinstance(v, _PydanticBaseModel):
                    result[k] = v.model_dump(**kw)
                elif hasattr(v, "model_dump"):
                    result[k] = v.model_dump(**kw)
                elif hasattr(v, "value"):
                    result[k] = v.value
                elif isinstance(v, list):
                    result[k] = [
                        x.model_dump(**kw) if isinstance(x, _PydanticBaseModel) else x for x in v
                    ]
                else:
                    result[k] = v
            return result

        @classmethod
        def model_rebuild(cls):
            pass

    _NOTHING = object()

    def _pydantic_Field(*args, **kw):
        if "default_factory" in kw:
            return kw["default_factory"]()
        if "default" in kw:
            return kw["default"]
        if args:
            return None
        return None

    def _pydantic_ConfigDict(**kw):
        return kw

    def _pydantic_field_validator(*a, **kw):
        def dec(fn):
            return classmethod(fn)

        return dec

    def _pydantic_model_validator(*a, **kw):
        def dec(fn):
            return fn

        return dec

    pydantic_mod = _make_module(
        "pydantic",
        BaseModel=_PydanticBaseModel,
        Field=_pydantic_Field,
        ConfigDict=_pydantic_ConfigDict,
        field_validator=_pydantic_field_validator,
        model_validator=_pydantic_model_validator,
        model_serializer=lambda fn: fn,
    )

    # -------------------------------------------------------------- #
    # ducta.mlrun / ducta.check / ducta.core  (thunk-based mocks)    #
    # -------------------------------------------------------------- #

    class _HyperparamConfig:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    def _load_hyperparams_config(*a, **kw):
        return _HyperparamConfig(source=str(a[0]) if a else "")

    ducta_mlrun_hyperparams = _make_module(
        "ducta.mlrun.hyperparams",
        HyperparamConfig=_HyperparamConfig,
        load_hyperparams_config=_load_hyperparams_config,
    )
    ducta_mlrun = _make_module(
        "ducta.mlrun",
        hyperparams=ducta_mlrun_hyperparams,
    )

    class _QualityOutputPath:
        def __init__(self, report_type="dq", node_name="n", output_path="/tmp/q"):
            self.report_type = report_type
            self.node_name = node_name
            self.output_path = output_path

    ducta_check = _make_module(
        "ducta.check",
        QualityOutputPath=_QualityOutputPath,
    )
    ducta_check_core = _make_module(
        "ducta.check.core",
        load_quality_extensions=lambda exts: None,
    )

    # ducta.core — lazily imported inside validators.py
    class _PipelineDependencyResolver:
        @staticmethod
        def validate_pipeline_dependencies(pipelines, depends_on_map=None):
            pass

    ducta_core_pdr = _make_module(
        "ducta.core.pipeline_dependency_resolver",
        PipelineDependencyResolver=_PipelineDependencyResolver,
    )

    ducta_core_di = _make_module(
        "ducta.core.dependency_inference",
        merge_pipeline_depends_on=lambda p, n: None,
    )

    ducta_core = _make_module(
        "ducta.core",
        pipeline_dependency_resolver=ducta_core_pdr,
        dependency_inference=ducta_core_di,
    )

    # -------------------------------------------------------------- #
    # databricks mocks (for session.py)                              #
    # -------------------------------------------------------------- #
    class _DatabricksSession:
        builder = None

        class builder:
            @staticmethod
            def remote(*a, **kw):
                return _DummyBuilder()

    class _DummyBuilder:
        def config(self, k, v):
            return self

        def getOrCreate(self):
            return MagicMock()

    class _DatabricksConfig:
        def __init__(self):
            self.host = "db-host"
            self.token = "db-token"
            self.cluster_id = "db-cluster"

    dc = _make_module("databricks.connect", DatabricksSession=_DatabricksSession)
    dsc = _make_module("databricks.sdk.core", Config=_DatabricksConfig)
    databricks = _make_module(
        "databricks", connect=dc, sdk=_make_module("databricks.sdk", core=dsc)
    )

    # pyspark mock (for session.py _create_local_session)
    _MockSparkSession = _types.new_class("SparkSession", (object,), {})
    _MockSparkSession.builder = _DummyBuilder
    ps_sql = _make_module("pyspark.sql", SparkSession=_MockSparkSession)
    pyspark = _make_module("pyspark", sql=ps_sql)

    # -------------------------------------------------------------- #
    # install all mocks into sys.modules                             #
    # -------------------------------------------------------------- #
    mappings = {
        "pydantic": pydantic_mod,
        "ducta.mlrun": ducta_mlrun,
        "ducta.mlrun.hyperparams": ducta_mlrun_hyperparams,
        "ducta.check": ducta_check,
        "ducta.check.core": ducta_check_core,
        "ducta.core": ducta_core,
        "ducta.core.pipeline_dependency_resolver": ducta_core_pdr,
        "ducta.core.dependency_inference": ducta_core_di,
        "databricks": databricks,
        "databricks.connect": dc,
        "databricks.sdk": _make_module("databricks.sdk", core=dsc),
        "databricks.sdk.core": dsc,
        "pyspark": pyspark,
        "pyspark.sql": ps_sql,
    }
    for name, mod in mappings.items():
        if name not in sys.modules:
            sys.modules[name] = mod


_install_mocks()


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def minimal_global_settings():
    return {
        "input_path": "/data/input",
        "output_path": "/data/output",
        "mode": "local",
    }


@pytest.fixture
def sample_pipelines_config():
    return {
        "pipeline_a": {
            "type": "batch",
            "nodes": ["node_a1", "node_a2"],
            "inputs": ["ds1"],
            "outputs": ["ds_out"],
        },
    }


@pytest.fixture
def sample_nodes_config():
    return {
        "node_a1": {
            "module": "mymod",
            "function": "mymod.my_func",
            "input": ["ds1"],
            "output": ["ds_out"],
        },
        "node_a2": {"module": "mymod", "function": "mymod.my_func2", "dependencies": ["node_a1"]},
    }


@pytest.fixture
def sample_input_config():
    return {
        "ds1": {"format": "parquet", "filepath": "/tmp/ds1.parquet"},
    }


@pytest.fixture
def sample_output_config():
    return {
        "ds_out": {"format": "parquet", "filepath": "/tmp/out.parquet", "write_mode": "overwrite"},
    }


@pytest.fixture
def mock_yaml_loader():
    """Replace YamlConfigLoader._load_format so it returns a canned dict."""
    with patch("ducta.setting.loaders.YamlConfigLoader._load_format") as m:
        m.return_value = {"key": "value"}
        yield m
