from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from ducta.setting.contexts import (
    BaseSpecializedContext,
    Context,
    ContextFactory,
    HybridContext,
    MLConfigMixin,
    MLContext,
    PipelineManager,
    StreamingContext,
)
from ducta.setting.exceptions import ConfigLoadError, ConfigValidationError
from ducta.setting.utils import deep_merge_dicts as _deep_merge_dicts


class TestDeepMergeDicts:
    def test_merge_simple(self):
        result = _deep_merge_dicts({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_merge_override(self):
        result = _deep_merge_dicts({"a": 1}, {"a": 2})
        assert result == {"a": 2}

    def test_merge_nested(self):
        result = _deep_merge_dicts({"a": {"b": 1}}, {"a": {"c": 2}})
        assert result == {"a": {"b": 1, "c": 2}}

    def test_merge_nested_override(self):
        result = _deep_merge_dicts({"a": {"b": 1}}, {"a": {"b": 2}})
        assert result == {"a": {"b": 2}}

    def test_original_not_mutated(self):
        base = {"a": 1}
        override = {"b": 2}
        _deep_merge_dicts(base, override)
        assert base == {"a": 1}

    def test_non_dict_override_replaces(self):
        result = _deep_merge_dicts({"a": {"b": 1}}, {"a": "string"})
        assert result == {"a": "string"}


class TestPipelineManager:
    def test_init(self):
        pm = PipelineManager({"p1": {"nodes": ["n1"]}}, {"n1": {}})
        assert pm.pipelines_config == {"p1": {"nodes": ["n1"]}}

    @patch("ducta.setting.validators.PipelineValidator.validate_pipeline_nodes")
    @patch("ducta.setting.validators.PipelineValidator.validate_pipeline_dependency_graph")
    def test_pipelines_property(self, mock_graph, mock_nodes):
        pm = PipelineManager(
            {"p1": {"nodes": ["n1"]}},
            {"n1": {"module": "mymod", "function": "mymod.my_func"}},
        )
        result = pm.pipelines
        assert "p1" in result
        assert result["p1"]["name"] == "p1"

    @patch("ducta.setting.validators.PipelineValidator.validate_pipeline_nodes")
    @patch("ducta.setting.validators.PipelineValidator.validate_pipeline_dependency_graph")
    def test_node_own_name_field_does_not_override_real_node_key(self, mock_graph, mock_nodes):
        """Regression: a node config carrying its own (extra) 'name' key must
        never shadow the actual node name it's referenced by in nodes list."""
        pm = PipelineManager(
            {"p1": {"nodes": ["n1"]}},
            {"n1": {"module": "mymod", "function": "mymod.my_func", "name": "spoofed"}},
        )
        result = pm.pipelines
        assert result["p1"]["nodes"][0]["name"] == "n1"

    def test_get_pipeline(self):
        pm = PipelineManager({"p1": {"nodes": []}}, {})
        with patch.object(type(pm), "pipelines", new_callable=PropertyMock) as mock_p:
            mock_p.return_value = {"p1": {"name": "p1"}}
            result = pm.get_pipeline("p1")
            assert result == {"name": "p1"}

    def test_list_pipeline_names(self):
        pm = PipelineManager({"p1": {"nodes": []}, "p2": {"nodes": []}}, {})
        with patch.object(type(pm), "pipelines", new_callable=PropertyMock) as mock_p:
            mock_p.return_value = {"p1": {}, "p2": {}}
            names = pm.list_pipeline_names()
            assert names == ["p1", "p2"]

    def test_get_pipelines_by_type(self):
        pm = PipelineManager(
            {
                "p1": {"nodes": [], "type": "batch"},
                "p2": {"nodes": [], "type": "ml"},
                "p3": {"nodes": []},
            },
            {},
        )
        batch = pm.get_pipelines_by_type("batch")
        assert "p1" in batch
        assert "p3" in batch
        assert "p2" not in batch


class TestMLConfigMixin:
    def test_default_hyperparams(self):
        ctx = MLConfigMixin()
        ctx.global_settings = {"default_hyperparams": {"lr": 0.01}}
        result = ctx.default_hyperparams
        assert result["lr"] == 0.01

    def test_default_hyperparams_empty(self):
        ctx = MLConfigMixin()
        ctx.global_settings = {}
        result = ctx.default_hyperparams
        assert result == {}

    def test_default_model_version(self):
        ctx = MLConfigMixin()
        ctx.global_settings = {"default_model_version": "1.0"}
        assert ctx.default_model_version == "1.0"

    def test_default_model_version_none(self):
        ctx = MLConfigMixin()
        ctx.global_settings = {}
        assert ctx.default_model_version is None

    def test_is_ml_layer_true(self):
        ctx = MLConfigMixin()
        ctx.layer = "ml"
        assert ctx.is_ml_layer is True

    def test_is_ml_layer_false(self):
        ctx = MLConfigMixin()
        ctx.layer = "batch"
        assert ctx.is_ml_layer is False

    def test_merge_hyperparams(self):
        mixin = MLConfigMixin()
        mixin.global_settings = {"default_hyperparams": {"lr": 0.01}}
        result = mixin._merge_hyperparams({"lr": 0.001, "epochs": 10})
        assert result == {"lr": 0.001, "epochs": 10}

    def test_get_node_ml_config(self):
        mixin = MLConfigMixin()
        mixin.nodes_config = {
            "n1": {"hyperparams": {"lr": 0.01}, "metrics": ["acc"], "description": "test"}
        }
        result = mixin.get_node_ml_config("n1")
        assert result["hyperparams"] == {"lr": 0.01}
        assert result["metrics"] == ["acc"]

    def test_get_node_ml_config_empty(self):
        mixin = MLConfigMixin()
        mixin.nodes_config = {}
        result = mixin.get_node_ml_config("nonexistent")
        assert result["hyperparams"] == {}

    def test_get_pipeline_ml_config(self):
        mixin = MLConfigMixin()
        mixin.pipelines_config = {"p1": {"hyperparams": {"epochs": 5}, "description": "test"}}
        mixin.global_settings = {"default_model_version": "1.0", "default_hyperparams": {}}
        result = mixin.get_pipeline_ml_config("p1")
        assert result["description"] == "test"

    def test_get_pipeline_ml_info(self):
        mixin = MLConfigMixin()
        mixin.ml_info = {"model_name": "base_model"}
        mixin.pipelines_config = {"p1": {}}
        mixin.global_settings = {
            "default_model_version": "1.0",
            "default_hyperparams": {},
            "project_name": "test_project",
        }
        result = mixin.get_pipeline_ml_info("p1")
        assert result["project_name"] == "test_project"
        assert result["model_name"] == "base_model"


class TestContextInit:
    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_from_json_config(self, mock_loader_cls, mock_get_session):
        mock_get_session.return_value = MagicMock()
        mock_loader = MagicMock()
        mock_loader.load_config.side_effect = lambda x: x if isinstance(x, dict) else {}
        mock_loader_cls.return_value = mock_loader

        with patch.object(Context, "_validate_all_configs_with_pydantic"):
            ctx = Context.from_json_config(
                global_settings={"input_path": "/in", "output_path": "/out", "mode": "local"},
                pipelines_config={"p1": {"nodes": ["n1"]}},
                nodes_config={"n1": {"function": "mymod.my_func"}},
                input_config={"ds1": {"format": "parquet"}},
                output_config={"out1": {"format": "delta"}},
            )
        assert ctx.global_settings["input_path"] == "/in"
        assert ctx.execution_mode == "local"
        assert ctx.layer == ""

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_from_processed(self, mock_loader_cls, mock_get_session):
        mock_get_session.return_value = MagicMock()
        mock_loader_cls.return_value = MagicMock()

        ctx = Context._from_processed(
            global_settings={"input_path": "/in", "output_path": "/out", "mode": "local"},
            pipelines_config={"p1": {"nodes": ["n1"]}},
            nodes_config={"n1": {"function": "mymod.my_func"}},
            input_config={"ds1": {"format": "parquet"}},
            output_config={"out1": {"format": "delta"}},
            env="dev",
        )
        assert ctx.global_settings["input_path"] == "/in"
        assert ctx.env == "dev"
        assert ctx._validate_with_pydantic is False

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_from_processed_with_ml_info(self, mock_loader_cls, mock_get_session):
        mock_get_session.return_value = MagicMock()
        mock_loader_cls.return_value = MagicMock()

        ctx = Context._from_processed(
            global_settings={"input_path": "/in", "output_path": "/out", "mode": "local"},
            pipelines_config={"p1": {"nodes": ["n1"]}},
            nodes_config={},
            input_config={},
            output_config={},
            ml_info={"model_name": "mymodel"},
        )
        assert ctx.ml_info["model_name"] == "mymodel"

    def test_prepare_sources(self):
        result = Context._prepare_sources(
            global_settings={"a": 1},
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
        )
        assert isinstance(result["global_settings"], dict)
        assert result["global_settings"]["a"] == 1

    def test_prepare_sources_string_to_path(self):
        result = Context._prepare_sources(
            global_settings="/path/to/file.yaml",
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
        )
        assert isinstance(result["global_settings"], Path)


class TestContextLazySpark:
    """`Context.spark` must not create a SparkSession until first real access —
    see the Phase 1 plan: constructing a Context (e.g. for `list-pipelines` or a
    quality-check-only pipeline) must not pay the Spark/JVM cost."""

    def _make_context(self, mock_loader_cls, mock_get_session):
        mock_get_session.return_value = MagicMock()
        mock_loader_cls.return_value = MagicMock()
        return Context._from_processed(
            global_settings={"input_path": "/in", "output_path": "/out", "mode": "local"},
            pipelines_config={"p1": {"nodes": ["n1"]}},
            nodes_config={"n1": {"function": "mymod.my_func"}},
            input_config={"ds1": {"format": "parquet"}},
            output_config={"out1": {"format": "delta"}},
        )

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_construction_does_not_create_session(self, mock_loader_cls, mock_get_session):
        self._make_context(mock_loader_cls, mock_get_session)
        mock_get_session.assert_not_called()

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_first_access_creates_session_once(self, mock_loader_cls, mock_get_session):
        ctx = self._make_context(mock_loader_cls, mock_get_session)
        session = ctx.spark
        assert session is mock_get_session.return_value
        mock_get_session.assert_called_once()

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_repeated_access_is_cached(self, mock_loader_cls, mock_get_session):
        ctx = self._make_context(mock_loader_cls, mock_get_session)
        first = ctx.spark
        second = ctx.spark
        assert first is second
        mock_get_session.assert_called_once()

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_has_spark_session_reflects_materialization(self, mock_loader_cls, mock_get_session):
        ctx = self._make_context(mock_loader_cls, mock_get_session)
        assert ctx.has_spark_session() is False
        ctx.spark  # noqa: B018 — trigger lazy creation
        assert ctx.has_spark_session() is True

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_explicit_spark_session_override_skips_factory(self, mock_loader_cls, mock_get_session):
        mock_loader_cls.return_value = MagicMock()
        injected = MagicMock(name="injected-session")
        ctx = Context._from_processed(
            global_settings={"input_path": "/in", "output_path": "/out", "mode": "local"},
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
            spark_session=injected,
        )
        assert ctx.has_spark_session() is True
        assert ctx.spark is injected
        mock_get_session.assert_not_called()

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_from_base_context_reuses_materialized_session(self, mock_loader_cls, mock_get_session):
        mock_get_session.return_value = MagicMock()
        base = self._make_context(mock_loader_cls, mock_get_session)
        base.spark  # materialize it on the base context
        mock_get_session.reset_mock()

        specialized = MLContext.from_base_context(base)

        assert specialized.spark is base.spark
        mock_get_session.assert_not_called()

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_from_base_context_does_not_force_unmaterialized_base(
        self, mock_loader_cls, mock_get_session
    ):
        mock_get_session.return_value = MagicMock()
        base = self._make_context(mock_loader_cls, mock_get_session)

        MLContext.from_base_context(base)

        # Building the specialized context must not have touched the base's
        # session — that's the whole point of checking has_spark_session()
        # instead of getattr(base_context, "spark", None).
        assert base.has_spark_session() is False
        mock_get_session.assert_not_called()


class TestContextQualityOutput:
    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_add_and_get_quality_outputs(self, mock_loader_cls, mock_get_session):
        mock_get_session.return_value = MagicMock()
        mock_loader_cls.return_value = MagicMock()

        ctx = Context._from_processed(
            global_settings={"input_path": "/in", "output_path": "/out", "mode": "local"},
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
        )
        from ducta.check import QualityOutputPath

        q1 = QualityOutputPath(
            report_type="dq",
            node_name="n1",
            run_id="r1",
            output_path="/tmp/q1",
            format="parquet",
            rows_written=10,
        )
        q2 = QualityOutputPath(
            report_type="sanity",
            node_name="n1",
            run_id="r1",
            output_path="/tmp/q2",
            format="parquet",
            rows_written=5,
        )
        ctx.add_quality_output_path(q1)
        ctx.add_quality_output_path(q2)
        assert len(ctx.quality_output_paths) == 2

        grouped = ctx.get_quality_outputs()
        assert "dq" in grouped
        assert "sanity" in grouped

        by_node = ctx.get_quality_outputs_by_node()
        assert "n1" in by_node
        assert len(by_node["n1"]) == 2


class TestContextEnvironmentOverrides:
    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_apply_overrides(self, mock_loader_cls, mock_get_session):
        mock_get_session.return_value = MagicMock()
        mock_loader_cls.return_value = MagicMock()

        ctx = Context._from_processed(
            global_settings={
                "input_path": "/in",
                "output_path": "/out",
                "mode": "local",
                "environments": {"dev": {"mode": "distributed"}},
            },
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
            env="dev",
        )
        ctx._apply_environment_overrides()
        assert ctx.global_settings.get("environment") == "dev"
        assert "environments" not in ctx.global_settings

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_no_override_without_env(self, mock_loader_cls, mock_get_session):
        mock_get_session.return_value = MagicMock()
        mock_loader_cls.return_value = MagicMock()

        ctx = Context._from_processed(
            global_settings={"input_path": "/in", "output_path": "/out", "mode": "local"},
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
        )
        ctx._apply_environment_overrides()

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    def test_merge_override_values(self, mock_loader_cls, mock_get_session):
        mock_get_session.return_value = MagicMock()
        mock_loader_cls.return_value = MagicMock()

        ctx = Context._from_processed(
            global_settings={
                "input_path": "/in",
                "output_path": "/out",
                "mode": "local",
                "environments": {"dev": {"mode": "distributed", "log_level": "DEBUG"}},
            },
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
            env="dev",
        )
        ctx._apply_environment_overrides()
        assert ctx.global_settings["mode"] == "distributed"
        assert ctx.global_settings["log_level"] == "DEBUG"
        assert ctx.global_settings["input_path"] == "/in"
        assert ctx.global_settings.get("environment") == "dev"


class TestMLContext:
    def test_is_compatible_node(self):
        assert MLContext._is_compatible_node(None, {"model": {}}) is True
        assert MLContext._is_compatible_node(None, {}) is False


class TestStreamingContext:
    def test_is_streaming_node_with_format_policy(self):
        ctx = StreamingContext.__new__(StreamingContext)
        from ducta.setting.validators import StreamingValidator

        ctx._validator = StreamingValidator()
        ctx.format_policy = ctx._validator.policy
        assert (
            ctx._is_streaming_node({"input": {"format": "kafka"}, "output": {"format": "delta"}})
            is True
        )

    def test_is_not_streaming_node(self):
        ctx = StreamingContext.__new__(StreamingContext)
        from ducta.setting.validators import StreamingValidator

        ctx._validator = StreamingValidator()
        ctx.format_policy = ctx._validator.policy
        assert ctx._is_streaming_node({"input": {"format": "parquet"}, "output": {}}) is False


class TestContextFactory:
    def test_create_context_batch(self):
        base = MagicMock(spec=Context)
        base.get_pipelines_by_type.side_effect = lambda t: {"bp": {}} if t == "batch" else {}
        result = ContextFactory.create_context(base)
        assert result is base

    def test_create_context_ml(self):
        base = MagicMock(spec=Context)
        base.get_pipelines_by_type.side_effect = lambda t: {"ml_p": {}} if t == "ml" else {}
        with patch("ducta.setting.contexts.MLContext.from_base_context", return_value="ml_ctx"):
            result = ContextFactory.create_context(base)
            assert result == "ml_ctx"

    def test_create_context_streaming(self):
        base = MagicMock(spec=Context)
        base.get_pipelines_by_type.side_effect = lambda t: {"str_p": {}} if t == "streaming" else {}
        with patch(
            "ducta.setting.contexts.StreamingContext.from_base_context", return_value="str_ctx"
        ):
            result = ContextFactory.create_context(base)
            assert result == "str_ctx"

    def test_create_context_hybrid(self):
        base = MagicMock(spec=Context)
        base.get_pipelines_by_type.side_effect = lambda t: (
            {"ml_p": {}} if t == "ml" else {"str_p": {}} if t == "streaming" else {}
        )
        with patch("ducta.setting.contexts.HybridContext") as mock_hc:
            mock_hc.return_value = "hybrid_ctx"
            result = ContextFactory.create_context(base)
            assert result == "hybrid_ctx"
