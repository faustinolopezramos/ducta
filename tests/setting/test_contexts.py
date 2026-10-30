from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from ducta.setting.contexts import (
    Context,
    MLConfigMixin,
    PipelineManager,
)
from ducta.setting.exceptions import ConfigLoadError, ConfigValidationError
from ducta.setting.interpolator import VariableInterpolator
from ducta.setting.validators import ConfigValidator, FormatPolicy


def _make_bare_context(
    global_config,
    pipelines_config,
    nodes_config,
    input_config,
    output_config,
    ml_info=None,
    spark_session=None,
    env=None,
):
    """Build a ``Context`` without running ``__init__``'s full load/validate/
    process pipeline — for tests that need a ``Context`` populated from
    already-final config dicts, to exercise one piece (e.g.
    ``_apply_environment``) in isolation. This used to be a
    production classmethod (``Context._from_processed``); it was removed as
    dead code (no production caller ever used the fast path), and this
    fixture-only helper took its place since only tests needed it."""
    obj = Context.__new__(Context)
    obj._validator = ConfigValidator()
    obj._interpolator = VariableInterpolator()
    obj._validate_with_pydantic = False
    obj.env = env
    obj.global_config = global_config
    obj.pipelines_config = pipelines_config
    obj.nodes_config = nodes_config
    obj.input_config = input_config
    obj.output_config = output_config
    obj.execution_mode = global_config.get("mode", "local")
    obj.input_path = global_config.get("input_path")
    obj.output_path = global_config.get("output_path")
    obj.ml_info = ml_info if isinstance(ml_info, dict) else {}
    obj.layer = global_config.get("layer", "").lower()
    obj.format_policy = FormatPolicy(obj.global_config.get("format_policy", {}))
    if spark_session is not None:
        obj.spark = spark_session
    obj._pipeline_manager = PipelineManager(obj.pipelines_config, obj.nodes_config)
    obj.quality_output_paths = []
    return obj


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
        ctx.global_config = {"default_hyperparams": {"lr": 0.01}}
        result = ctx.default_hyperparams
        assert result["lr"] == 0.01

    def test_default_hyperparams_empty(self):
        ctx = MLConfigMixin()
        ctx.global_config = {}
        result = ctx.default_hyperparams
        assert result == {}

    def test_default_model_version(self):
        ctx = MLConfigMixin()
        ctx.global_config = {"default_model_version": "1.0"}
        assert ctx.default_model_version == "1.0"

    def test_default_model_version_none(self):
        ctx = MLConfigMixin()
        ctx.global_config = {}
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
        mixin.global_config = {"default_hyperparams": {"lr": 0.01}}
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
        mixin.global_config = {"default_model_version": "1.0", "default_hyperparams": {}}
        result = mixin.get_pipeline_ml_config("p1")
        assert result["description"] == "test"

    def test_get_pipeline_ml_info(self):
        mixin = MLConfigMixin()
        mixin.ml_info = {"model_name": "base_model"}
        mixin.pipelines_config = {"p1": {}}
        mixin.global_config = {
            "default_model_version": "1.0",
            "default_hyperparams": {},
            "project_name": "test_project",
        }
        result = mixin.get_pipeline_ml_info("p1")
        assert result["project_name"] == "test_project"
        assert result["model_name"] == "base_model"

    @patch("ducta.mlrun.hyperparams.load_hyperparams_config")
    def test_resolve_hyperparams_config_skips_non_ml_pipeline(self, mock_load):
        """A global hyperparams_config_path must not be resolved for a batch
        pipeline — only type=="ml" pipelines may fall back to the path-only
        (no pipeline_key) branch. Regression for a spurious "pipeline_key is
        required" error logged on every non-ML pipeline run."""
        mixin = MLConfigMixin()
        mixin.ml_info = {}
        mixin.pipelines_config = {"bronze.ingestion": {"type": "batch"}}
        mixin.global_config = {"hyperparams_config_path": "config/ml/hyperparams.yml"}

        result = mixin._resolve_hyperparams_config("bronze.ingestion")

        assert result is None
        mock_load.assert_not_called()

    @patch("ducta.mlrun.hyperparams.load_hyperparams_config")
    def test_resolve_hyperparams_config_still_resolves_ml_pipeline(self, mock_load):
        mixin = MLConfigMixin()
        mixin.ml_info = {}
        mixin.pipelines_config = {"ml.student_performance": {"type": "ml"}}
        mixin.global_config = {"hyperparams_config_path": "config/ml/hyperparams.yml"}

        mixin._resolve_hyperparams_config("ml.student_performance")

        # required=False: a file with several keys and none named means no search.
        mock_load.assert_called_once_with("config/ml/hyperparams.yml", required=False)


class TestContextLazySpark:
    """`Context.spark` must not create a SparkSession until first real access —
    see the Phase 1 plan: constructing a Context (e.g. for `list-pipelines` or a
    quality-check-only pipeline) must not pay the Spark/JVM cost."""

    def _make_context(self, mock_get_session):
        mock_get_session.return_value = MagicMock()
        return _make_bare_context(
            global_config={"input_path": "/in", "output_path": "/out", "mode": "local"},
            pipelines_config={"p1": {"nodes": ["n1"]}},
            nodes_config={"n1": {"function": "mymod.my_func"}},
            input_config={"ds1": {"format": "parquet"}},
            output_config={"out1": {"format": "delta"}},
        )

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    def test_construction_does_not_create_session(self, mock_get_session):
        self._make_context(mock_get_session)
        mock_get_session.assert_not_called()

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    def test_first_access_creates_session_once(self, mock_get_session):
        ctx = self._make_context(mock_get_session)
        session = ctx.spark
        assert session is mock_get_session.return_value
        mock_get_session.assert_called_once()

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    def test_repeated_access_is_cached(self, mock_get_session):
        ctx = self._make_context(mock_get_session)
        first = ctx.spark
        second = ctx.spark
        assert first is second
        mock_get_session.assert_called_once()

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    def test_has_spark_session_reflects_materialization(self, mock_get_session):
        ctx = self._make_context(mock_get_session)
        assert ctx.has_spark_session() is False
        ctx.spark  # noqa: B018 — trigger lazy creation
        assert ctx.has_spark_session() is True

    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    def test_explicit_spark_session_override_skips_factory(self, mock_get_session):
        injected = MagicMock(name="injected-session")
        ctx = _make_bare_context(
            global_config={"input_path": "/in", "output_path": "/out", "mode": "local"},
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
            spark_session=injected,
        )
        assert ctx.has_spark_session() is True
        assert ctx.spark is injected
        mock_get_session.assert_not_called()


def _documents(**global_overrides):
    return dict(
        global_config={
            "input_path": "/in",
            "output_path": "/out",
            "mode": "local",
            **global_overrides,
        },
        pipelines_config={"p1": {"nodes": ["n1"]}},
        nodes_config={"n1": {"function": "mymod.my_func"}},
        input_config={"ds1": {"format": "parquet"}},
        output_config={"out1": {"format": "delta"}},
    )


class TestContextInit:
    def test_builds_from_the_five_documents(self):
        ctx = Context(**_documents(), validate=False)
        assert ctx.global_config["input_path"] == "/in"
        assert ctx.execution_mode == "local"
        assert ctx.list_pipeline_names() == ["p1"]
        assert ctx.layer == ""
        assert ctx.ml_info == {"hyperparams": {}}

    def test_creating_it_does_not_start_spark(self):
        with patch("ducta.setting.contexts.SparkSessionFactory.get_session") as get_session:
            ctx = Context(**_documents(), validate=False)
        get_session.assert_not_called()
        assert ctx.has_spark_session() is False

    @pytest.mark.parametrize(
        "document",
        ["global_config", "pipelines_config", "nodes_config", "input_config", "output_config"],
    )
    def test_each_document_must_be_a_mapping(self, document):
        docs = _documents()
        docs[document] = "path/to/file.yaml"
        with pytest.raises(ConfigValidationError, match="must be of type dict"):
            Context(**docs, validate=False)

    def test_global_config_requires_paths_and_mode(self):
        docs = _documents()
        del docs["global_config"]["output_path"]
        with pytest.raises(ConfigValidationError, match="output_path"):
            Context(**docs, validate=False)

    def test_ml_info_must_be_a_mapping(self):
        with pytest.raises(ConfigValidationError, match="ml_info must be a mapping"):
            Context(**_documents(), ml_info="ml.yaml", validate=False)

    def test_inline_ml_info_is_used(self):
        ctx = Context(**_documents(), ml_info={"model_name": "churn"}, validate=False)
        assert ctx.ml_info["model_name"] == "churn"


class TestContextEnvironment:
    def test_env_argument_is_normalised_and_recorded(self):
        ctx = Context(**_documents(), env="Production", validate=False)
        assert ctx.global_config["environment"] == "prod"

    def test_environment_named_in_the_config_is_kept(self):
        ctx = Context(**_documents(environment="dev"), validate=False)
        assert ctx.global_config["environment"] == "dev"

    def test_env_argument_wins_over_the_config(self):
        ctx = Context(**_documents(environment="dev"), env="staging", validate=False)
        assert ctx.global_config["environment"] == "staging"

    def test_no_environment_records_nothing(self):
        ctx = Context(**_documents(), validate=False)
        assert "environment" not in ctx.global_config


class TestEnvironmentCannotLeaveTheOutputPath:
    """``env`` names the folders a run writes to; ``../../x`` must not load."""

    @pytest.mark.parametrize("env", ["../../../../escape", "/etc", "a/../b", ".."])
    def test_a_hostile_env_is_refused_at_load(self, env):
        with pytest.raises(ConfigValidationError, match="Invalid environment"):
            Context(**_documents(), env=env, validate=False)

    def test_a_hostile_environment_in_the_config_is_refused_too(self):
        with pytest.raises(ConfigValidationError, match="Invalid environment"):
            Context(**_documents(environment="../x"), validate=False)

    @pytest.mark.parametrize("env", ["dev", "prod", "sandbox_ana", "dev.eu"])
    def test_ordinary_names_still_load(self, env):
        assert Context(**_documents(), env=env, validate=False).global_config["environment"] == env

    def test_a_real_project_refuses_it_too(self, tmp_path):
        import ducta

        (tmp_path / "ducta.yaml").write_text(
            "version: 2\nproject: demo\npaths: {input: d, output: d}\n"
        )
        (tmp_path / "catalog.yaml").write_text(
            "silver.sales.orders: {format: parquet}\nraw: {format: csv, path: d/r}\n"
        )
        (tmp_path / "pipelines").mkdir()
        (tmp_path / "pipelines" / "p.yaml").write_text(
            "nodes:\n  n:\n    run: src.m:f\n    inputs: [raw]\n    outputs: [silver.sales.orders]\n"
        )
        with pytest.raises(Exception, match="Invalid environment"):
            ducta.load_project(tmp_path, env="../../../../escape")
        assert ducta.load_project(tmp_path, env="dev").global_config["environment"] == "dev"


class TestMlInfo:
    def test_one_refused_value_does_not_leave_the_rest_uninterpolated(self):
        docs = _documents(environment="dev")
        ml_info = {
            "model_name": "churn_${environment}",
            "registry": {"token": "${REGISTRY_TOKEN}", "uri": "s3://${environment}/models"},
            "tags": ["${environment}", "${API_KEY}"],
        }
        ctx = Context(**docs, ml_info=ml_info, validate=False)
        assert ctx.ml_info["model_name"] == "churn_dev"
        assert ctx.ml_info["registry"]["uri"] == "s3://dev/models"
        assert ctx.ml_info["registry"]["token"] == "${REGISTRY_TOKEN}"  # refused, left as written
        assert ctx.ml_info["tags"] == ["dev", "${API_KEY}"]

    def test_a_path_gets_a_migration_hint(self):
        from ducta.setting.schemas import GlobalConfigSchema

        with pytest.raises(ValueError, match="Move that file's content under settings.ml_info"):
            GlobalConfigSchema.model_validate(
                {"input_path": "/in", "output_path": "/out", "ml_info": "config/ml.yaml"}
            )
