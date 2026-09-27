import pytest

from ducta.setting.schemas import (
    ChainReuseConfig,
    ConfigSchema,
    DataQualitySchema,
    ExecutionMode,
    GlobalConfigSchema,
    InputFormat,
    InputSchema,
    LogLevel,
    MLStage,
    NodeSchema,
    OutputFormat,
    OutputSchema,
    PipelineSchema,
    PipelineType,
    ProjectSchema,
    QualityCheckEntrySchema,
    QualityGateSchema,
    QualityGlobalConfig,
    QualityOutputSchema,
    QualityProfileSchema,
    SanityChecksSchema,
    SplitConfig,
    WriteMode,
)


class TestProjectSchema:
    def test_minimal(self):
        s = ProjectSchema(name="my_project")
        assert s.name == "my_project"

    def test_full(self):
        s = ProjectSchema(
            name="my_project",
            description="A project",
            variables={"key": "val"},
            metadata={"owner": "team"},
            created_at="2024-01-01",
            updated_at="2024-06-01",
        )
        assert s.name == "my_project"
        assert s.description == "A project"


class TestGlobalConfigSchema:
    def test_required_fields(self):
        s = GlobalConfigSchema(input_path="/in", output_path="/out")
        assert s.input_path == "/in"
        assert s.output_path == "/out"
        assert s.mode == ExecutionMode.LOCAL
        assert s.log_level == LogLevel.INFO

    def test_defaults(self):
        s = GlobalConfigSchema(input_path="/in", output_path="/out")
        assert s.max_parallel_nodes == 4
        assert s.execution_timeout_seconds == 3600
        assert s.fingerprint_mode == "auto"
        # None, not True: unset means "decide per pipeline" (track pipelines that
        # contain ML nodes). A True default would survive model_dump and reach
        # the engine as though the user had asked for tracking everywhere.
        assert s.mlops_enabled is None
        assert s.mlops_required is False
        assert s.ml_default_sanity_checks is True

    def test_to_dicts_via_config_schema(self):
        gs = GlobalConfigSchema(input_path="/in", output_path="/out", mode=ExecutionMode.LOCAL)
        config = ConfigSchema(
            global_config=gs,
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
        )
        d = config.to_dicts()
        assert d["global_config"]["input_path"] == "/in"
        assert d["global_config"]["output_path"] == "/out"

    def test_run_certificate_dir_empty_string_rejected(self):
        """Regression: run_certificate_dir had no validator at all — unlike
        input_path/output_path, an empty string passed straight through."""
        with pytest.raises(Exception, match="non-empty string"):
            GlobalConfigSchema(input_path="/in", output_path="/out", run_certificate_dir="")

    def test_run_certificate_dir_default_and_override(self):
        # The schema only validates the raw string; ${output_path}/${environment}
        # interpolation and per-environment scoping happen later, in
        # CoreSettings._resolve_scoped_dir (see tests/core/test_certificate.py).
        s = GlobalConfigSchema(input_path="/in", output_path="/out")
        assert s.run_certificate_dir == "${output_path}/${environment}/.ducta/runs"
        s2 = GlobalConfigSchema(
            input_path="/in", output_path="/out", run_certificate_dir="custom/runs"
        )
        assert s2.run_certificate_dir == "custom/runs"


class TestNodeSchema:
    def test_minimal(self):
        s = NodeSchema()
        assert s.retry == 0
        assert s.dependencies == []

    def test_validate_module_function_ok_with_module(self):
        s = NodeSchema(function="my_func", module="mymod")
        assert s.function == "my_func"

    def test_validate_module_function_ok_dotted(self):
        s = NodeSchema(function="mymod.my_func")
        assert s.function == "mymod.my_func"


class TestPipelineSchema:
    def test_required_nodes(self):
        s = PipelineSchema(nodes=["n1", "n2"])
        assert s.nodes == ["n1", "n2"]
        assert s.type == PipelineType.BATCH

    def test_defaults(self):
        s = PipelineSchema(nodes=["n1"])
        assert s.requires_dates is True
        assert s.inputs == []
        assert s.outputs == []


class TestInputSchema:
    def test_required_format(self):
        s = InputSchema(format=InputFormat.PARQUET)
        assert s.format == InputFormat.PARQUET

    def test_with_filepath(self):
        s = InputSchema(format=InputFormat.CSV, filepath="/data/input.csv")
        assert s.filepath == "/data/input.csv"


class TestOutputSchema:
    def test_required_format(self):
        s = OutputSchema(format=OutputFormat.DELTA)
        assert s.format == OutputFormat.DELTA
        assert s.write_mode == WriteMode.APPEND

    def test_overwrite_mode(self):
        s = OutputSchema(format=OutputFormat.PARQUET, write_mode=WriteMode.OVERWRITE)
        assert s.write_mode == WriteMode.OVERWRITE


class TestConfigSchema:
    def test_roundtrip(self):
        config = ConfigSchema(
            global_config=GlobalConfigSchema(input_path="/in", output_path="/out"),
            pipelines_config={
                "p1": PipelineSchema(nodes=["n1"]),
            },
            nodes_config={
                "n1": NodeSchema(function="mymod.my_func"),
            },
            input_config={
                "ds1": InputSchema(format=InputFormat.PARQUET, filepath="/data/ds1.parquet"),
            },
            output_config={
                "out1": OutputSchema(format=OutputFormat.DELTA),
            },
        )
        d = config.to_dicts()
        assert d["global_config"]["input_path"] == "/in"
        assert "p1" in d["pipelines_config"]
        assert "n1" in d["nodes_config"]
        assert "ds1" in d["input_config"]
        assert "out1" in d["output_config"]


class TestEnums:
    def test_execution_mode_values(self):
        assert ExecutionMode.LOCAL.value == "local"
        assert ExecutionMode.DATABRICKS.value == "databricks"
        assert ExecutionMode.DISTRIBUTED.value == "distributed"

    def test_pipeline_type_values(self):
        assert PipelineType.BATCH.value == "batch"
        assert PipelineType.ML.value == "ml"
        assert PipelineType.STREAMING.value == "streaming"
        assert PipelineType.HYBRID.value == "hybrid"

    def test_input_format_values(self):
        assert InputFormat.PARQUET.value == "parquet"
        assert InputFormat.DELTA.value == "delta"
        assert InputFormat.KAFKA.value == "kafka"

    def test_output_format_values(self):
        assert OutputFormat.PARQUET.value == "parquet"
        assert OutputFormat.DELTA.value == "delta"
        assert OutputFormat.KAFKA.value == "kafka"
        assert OutputFormat.UNITY_CATALOG.value == "unity_catalog"

    def test_write_mode_values(self):
        assert WriteMode.OVERWRITE.value == "overwrite"
        assert WriteMode.APPEND.value == "append"
        assert WriteMode.MERGE.value == "merge"

    def test_log_level_values(self):
        assert LogLevel.INFO.value == "INFO"
        assert LogLevel.DEBUG.value == "DEBUG"

    def test_ml_stage_values(self):
        assert MLStage.TRAINING.value == "training"
        assert MLStage.SERVING.value == "serving"


class TestQualitySchemas:
    def test_quality_check_entry(self):
        s = QualityCheckEntrySchema()
        assert s.enabled is True

    def test_quality_profile(self):
        s = QualityProfileSchema()
        assert s.checks == {}

    def test_quality_output(self):
        s = QualityOutputSchema()
        assert s.enabled is False
        assert s.format == "parquet"

    def test_quality_gate_defaults(self):
        s = QualityGateSchema()
        assert s.name == "quality_gate"
        assert s.max_errors == 0
        # 0.0 = rule off, matching QualityGateEvaluator's own default. These two
        # defaults must agree: see tests/check/test_gate_schema_seam.py.
        assert s.min_pass_rate == 0.0
        assert s.behavior == "skip_downstream"

    def test_quality_global_config(self):
        s = QualityGlobalConfig()
        assert s.extensions == []
        assert s.profiles == {}

    def test_sanity_checks_defaults(self):
        s = SanityChecksSchema()
        assert s.enabled is True
        assert s.fail_fast is True
        assert s.input_index == 0

    def test_data_quality_defaults(self):
        s = DataQualitySchema()
        assert s.enabled is True
        assert s.fail_fast is False
        assert s.checks == {}


class TestChainReuseConfig:
    def test_defaults(self):
        s = ChainReuseConfig()
        assert s.reuse_materialized is False
        # Reuse is opt-in, so once a user asks for it the freshness check that
        # keeps it honest is on. Must match CoreSettings.chain_staleness_check:
        # Context replaces global_config with this schema's model_dump, and
        # exclude_none does not drop a False, so a disagreeing default here
        # silently overrides the engine's. See
        # tests/core/test_settings.py::TestSchemaDefaultsDoNotDrift.
        assert s.staleness_check is True


class TestSplitConfig:
    def test_defaults(self):
        s = SplitConfig()
        assert s.method == "random"
        assert s.test_size == 0.2
        assert s.val_size is None
