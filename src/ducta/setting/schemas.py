"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from loguru import logger  # type: ignore
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectSchema(BaseModel):
    """
    Schema for project_settings.yaml — the file that marks a directory as a
    Ducta project and stores project-level metadata.
    """

    name: str = Field(..., description="Project identifier (slug)", min_length=1, max_length=64)
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description of the project's purpose",
        max_length=500,
    )
    variables: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Shared key/value variables available to all pipelines in this project. "
            "These are merged with (and may override) workspace-level globals."
        ),
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arbitrary metadata for documentation/governance (e.g. team, cost_center, owner, sla)."
        ),
    )
    created_at: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp of project creation",
    )
    updated_at: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp of last settings update",
    )

    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
        extra="allow",
    )


class ExecutionMode(str, Enum):
    """Supported execution modes."""

    LOCAL = "local"
    DATABRICKS = "databricks"
    DISTRIBUTED = "distributed"


class PipelineType(str, Enum):
    """Pipeline types."""

    BATCH = "batch"
    ML = "ml"
    STREAMING = "streaming"
    HYBRID = "hybrid"


class MLStage(str, Enum):
    """Explicit ML lifecycle stage for a node."""

    FEATURE_ENGINEERING = "feature_engineering"
    TRAINING = "training"
    EVALUATION = "evaluation"
    SERVING = "serving"


class InputFormat(str, Enum):
    """Supported input formats."""

    PARQUET = "parquet"
    DELTA = "delta"
    CSV = "csv"
    JSON = "json"
    KAFKA = "kafka"
    KINESIS = "kinesis"
    AVRO = "avro"
    ORC = "orc"
    XML = "xml"
    QUERY = "query"


class OutputFormat(str, Enum):
    """Supported output formats."""

    PARQUET = "parquet"
    DELTA = "delta"
    CSV = "csv"
    JSON = "json"
    KAFKA = "kafka"
    PICKLE = "pickle"
    ORC = "orc"
    AVRO = "avro"
    XML = "xml"
    QUERY = "query"
    UNITY_CATALOG = "unity_catalog"


class WriteMode(str, Enum):
    """Write modes for outputs."""

    OVERWRITE = "overwrite"
    APPEND = "append"
    IGNORE = "ignore"
    ERROR = "error"
    MERGE = "merge"


class LogLevel(str, Enum):
    """Logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ChainReuseConfig(BaseModel):
    """Configuration for reusing already-materialized upstream pipelines."""

    reuse_materialized: bool = Field(
        default=False,
        description=(
            "Skip an upstream pipeline in a depends_on chain when all its outputs "
            "are already materialized (batch pipelines with overwrite outputs only). "
            "Default false preserves the always-rerun behavior."
        ),
    )
    staleness_check: bool = Field(
        default=True,
        description=(
            "Additionally require outputs to be newer than the pipeline's file "
            "inputs before skipping. No effect unless reuse_materialized is true; "
            "sources without a file mtime (DB/Kafka/cloud) fall back to existence. "
            "Must stay in step with CoreSettings.chain_staleness_check: Context "
            "replaces global_config with this schema's model_dump, and "
            "exclude_none does not drop a False, so a default that disagrees here "
            "silently overrides the one the engine resolves."
        ),
    )
    state_dir: str = Field(
        default="${output_path}/${environment}/.ducta/chain_state",
        description=(
            "Directory where chain-state markers (the date range a batch "
            "pipeline last ran, for reuse_materialized) are written. Same "
            "interpolation and env-scoping rules as global_config."
            "run_certificate_dir — see the Ducta storage convention there."
        ),
    )

    model_config = ConfigDict(extra="allow")


#: Keys the framework itself writes into `global_config` at runtime (after the
#: user's file has been validated). They are not typos and must never be warned
#: about, even if a future refactor makes validation see them.
_RUNTIME_GLOBAL_CONFIG_KEYS = frozenset({"environment", "pipeline_name", "layer", "mlops"})


def _warn_unknown_keys(model: BaseModel, block: str) -> None:
    """Log a warning for keys the schema does not declare, with a near-match hint.

    Every config schema here sets ``extra="allow"``, which is load-bearing: it is
    how forward-compatible and third-party keys survive a round-trip through
    validation. The cost is that a misspelling is indistinguishable from an
    intentional extra — `max_paralel_nodes` validated clean and the pipeline ran
    on the default of 4, with nothing said. Warning (rather than rejecting)
    keeps the escape hatch open while making the typo visible.
    """
    extras = getattr(model, "model_extra", None)
    if not extras:
        return
    unknown = sorted(set(extras) - _RUNTIME_GLOBAL_CONFIG_KEYS)
    if not unknown:
        return

    import difflib

    known = list(type(model).model_fields)
    for key in unknown:
        close = difflib.get_close_matches(key, known, n=1, cutoff=0.8)
        if close:
            logger.warning(
                "Unknown key '{}' in {} — did you mean '{}'? It is being kept as-is "
                "and ignored by Ducta.",
                key,
                block,
                close[0],
            )
        else:
            logger.warning(
                "Unknown key '{}' in {} — Ducta does not read it. Remove it, or "
                "ignore this if it is consumed by your own code.",
                key,
                block,
            )


class GlobalConfigSchema(BaseModel):
    """Validated global config configuration."""

    input_path: str = Field(..., description="Base input directory path", min_length=1)
    output_path: str = Field(..., description="Base output directory path", min_length=1)
    mode: ExecutionMode = Field(
        default=ExecutionMode.LOCAL, description="Execution mode: local, databricks, or distributed"
    )
    max_parallel_nodes: int = Field(
        default=4, ge=1, le=128, description="Maximum parallel node execution (1-128)"
    )
    max_input_workers: Optional[int] = Field(
        default=None, ge=1, le=64, description="Concurrency limit for parallel input reads"
    )
    in_memory_handoff: bool = Field(
        default=False,
        description=(
            "Pass a node's output to its dependants in memory instead of re-reading "
            "it from disk. Spark frames are persisted MEMORY_AND_DISK and spill; "
            "pandas frames are held as deep copies for the whole run, so peak memory "
            "grows with the number of handed-off nodes."
        ),
    )
    fill_none_on_error: bool = Field(
        default=False,
        description="Yield None for an input that fails to load instead of raising",
    )
    execution_timeout_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Execution timeout in seconds (60 secs to 24 hours)",
    )
    project_name: Optional[str] = Field(default=None, description="Project name for MLOps tracking")
    default_model_version: Optional[str] = Field(
        default=None, description="Default ML model version"
    )
    log_level: LogLevel = Field(default=LogLevel.INFO, description="Logging level")
    spark_config: Optional[Dict[str, Any]] = Field(
        default=None, description="Spark configuration overrides"
    )
    format_policy: Optional[Dict[str, Any]] = Field(
        default=None, description="Format policy for inputs/outputs"
    )

    @model_validator(mode="after")
    def _flag_unknown_keys(self) -> "GlobalConfigSchema":
        _warn_unknown_keys(self, "global_config")
        return self

    ml_info: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None,
        description="ML info configuration: inline dict or path to a YAML/JSON/TOML file",
    )
    streaming_transform_modules: Optional[List[str]] = Field(
        default=None,
        description=(
            "Python module paths whose register_transforms(registry) function is called "
            "automatically before any streaming or hybrid pipeline starts. "
            "Equivalent to passing --transforms-modules in the CLI. "
            "Example: ['myproject.transforms', 'nodes.silver_clean']"
        ),
    )
    quality: Optional["QualityGlobalConfig"] = Field(
        default=None,
        description=(
            "Quality module configuration: custom extension modules and reusable profiles. "
            "Extensions are auto-loaded at startup; profiles are merged into node checks."
        ),
    )
    chain: Optional[ChainReuseConfig] = Field(
        default=None,
        description=(
            "Chain-reuse configuration: skip already-materialized upstream pipelines "
            "in a depends_on chain instead of recomputing them on every run."
        ),
    )

    # Data lineage configuration
    enable_data_fingerprinting: bool = Field(
        default=True, description="Enable data fingerprinting for lineage tracking"
    )
    fingerprint_mode: str = Field(
        default="auto",
        description=(
            "How much of a dataset the fingerprint covers. 'auto' (default): cost "
            "proportional to what the run processed — a Delta input by its commit "
            "version (no scan), an input with an incremental window by every row of "
            "the window, any other input by every row up to fingerprint_exact_max_bytes "
            "and by a sample above it; outputs by every row of the written batch. "
            "'exact' (every row, order-independent), 'exact_crypto' (same, SHA-256), "
            "'sample' (the N rows with the lowest row hash, chosen by content) or "
            "'schema' (schema and row count, no content) force one strategy. The "
            "legacy names 'fast' and 'full' still parse."
        ),
    )
    fingerprint_exact_max_bytes: Optional[int] = Field(
        default=None,
        description=(
            "Under fingerprint_mode 'auto', the largest input (bytes on disk) hashed "
            "in full; larger inputs without an incremental window are sampled. "
            "Default 10 GiB."
        ),
    )
    fingerprint_sample_rows: int = Field(
        default=100, description="Rows covered when fingerprint_mode='sample'"
    )
    fingerprint_policy: Literal["record", "warn", "fail"] = Field(
        default="record",
        description=(
            "Action when an input's fingerprint differs from the previous successful run "
            "of the same pipeline: 'record' (lineage only), 'warn' (log a warning), "
            "'fail' (abort the node before executing on changed data)"
        ),
    )

    # Keys CoreSettings reads (core/settings.py) that were missing here, so
    # setting any of them triggered a false "Unknown key … Ducta does not read
    # it" warning. `None` defaults on purpose: the validated config is dumped
    # back into the Context, and a concrete default would reach CoreSettings
    # as though the user had typed it. CoreSettings owns the real defaults.
    # tests/setting/test_schema_covers_core_settings.py keeps the two in sync.
    start_date: Optional[str] = Field(default=None, description="Default run start date.")
    end_date: Optional[str] = Field(default=None, description="Default run end date.")
    env: Optional[str] = Field(default=None, description="Environment name override.")
    project_id: Optional[str] = Field(default=None, description="Project identifier.")
    node_timeout_seconds: Optional[int] = Field(
        default=None, description="Per-node time limit in seconds (default 1800, max 86400)."
    )
    checkpoints_base: Optional[str] = Field(
        default=None,
        description="Base directory for stream checkpoints of nodes without their own "
        "checkpoint_location (default: <output_path>/<environment>/streaming_checkpoints).",
    )
    streaming_node_start_retries: Optional[int] = Field(
        default=None, description="Attempts to start a stream node's query (default 45)."
    )
    streaming_node_start_retry_delay_seconds: Optional[float] = Field(
        default=None, description="Seconds between those attempts (default 2)."
    )
    streaming_node_start_parallelism: Optional[int] = Field(
        default=None, description="Stream nodes of one wave started concurrently (default 8)."
    )
    streaming_status_cache_ttl_seconds: Optional[float] = Field(
        default=None, description="How long a streaming status snapshot is reused (default 2)."
    )
    streaming_disable_backpressure_defaults: Optional[bool] = Field(
        default=None,
        description="Do not add Ducta's default rate limits (maxFilesPerTrigger, "
        "maxOffsetsPerTrigger) to stream sources that set none (default false).",
    )
    streaming_adaptive_base_interval: Optional[str] = Field(
        default=None,
        description="Starting interval of an 'adaptive' trigger with no history yet (default '5 seconds').",
    )
    streaming_adaptive_max_interval_seconds: Optional[float] = Field(
        default=None, description="Ceiling of an 'adaptive' trigger's interval (default 60)."
    )
    streaming_shuffle_partitions: Optional[int] = Field(
        default=None, description="spark.sql.shuffle.partitions applied to streaming queries."
    )
    mlops_path: Optional[str] = Field(
        default=None, description="Where MLOps experiments and models are stored."
    )
    mlops_storage_path: Optional[str] = Field(
        default=None, description="Fallback MLOps storage path for the CLI commands."
    )
    model_registry_path: Optional[str] = Field(
        default=None, description="Local directory where model artifacts are copied on write."
    )
    max_streaming_pipelines: Optional[int] = Field(
        default=None, description="Maximum concurrent streaming pipelines (default 5)."
    )
    preflight_enabled: Optional[bool] = Field(
        default=None, description="Validate configuration before running (default true)."
    )
    strict_module_import: Optional[bool] = Field(
        default=None,
        description="Only import node modules under allowed prefixes (default true).",
    )
    mlflow: Optional[Dict[str, Any]] = Field(default=None, description="MLflow bridge settings.")
    ingestion: Optional[Dict[str, Any]] = Field(
        default=None, description="Ingestion node defaults."
    )
    run_lock: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Exclusive lock on each output dataset for the duration of a run: "
            "{enabled: true, backend: local|storage, ttl_seconds: 300, "
            "on_conflict: fail|wait, wait_timeout_seconds: 600, dir: <path or s3://…>}. "
            "'local' (default) is an OS lock, one host; 'storage' is a renewed lease "
            "on a shared filesystem or S3, for several hosts."
        ),
    )
    delta_package: Optional[str] = Field(
        default=None,
        description=(
            "Maven coordinate of the Delta Lake jar for local sessions (default: the "
            "build matching the installed PySpark, e.g. io.delta:delta-spark_2.12:3.2.1)"
        ),
    )
    fail_on_error: Optional[bool] = Field(
        default=None,
        description="Whether a failed dataset write aborts the node (default true).",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Free-form project metadata (version, template, owner, …). Not read by Ducta.",
    )

    # Run Certificate — a tamper-evident record emitted per terminating run
    evidence_level: Optional[str] = Field(
        default=None,
        description=(
            "How much evidence each run must leave: 'off' (no certificate), 'record' "
            "(default — written, a write failure only warns), 'required' (a run that "
            "cannot write its certificate fails), 'signed' (required + HMAC-signed; "
            "preflight fails without DUCTA_CERTIFICATE_KEY)"
        ),
    )
    certificate_signing_key: Optional[str] = Field(
        default=None,
        description="HMAC signing key. Prefer the DUCTA_CERTIFICATE_KEY environment "
        "variable: a key in a config file is usually committed.",
    )
    run_certificate_dir: str = Field(
        default="${output_path}/${environment}/.ducta/runs",
        description=(
            "Directory where Run Certificates are written. Supports "
            "${output_path}/${environment} interpolation (the Ducta storage "
            "convention: framework-managed state lives under the environment's "
            "data tree, hidden in a `.ducta/` namespace, next to "
            "`${output_path}/${environment}/quality`). A value without "
            "${environment} is still scoped per environment automatically, by "
            "appending it as a path segment."
        ),
    )

    # Reproducibility
    random_seed: Optional[int] = Field(
        default=None, description="Global random seed for reproducibility"
    )

    hyperparams_config_path: Optional[str] = Field(
        default=None,
        description=(
            "Path to the hyperparameter search config YAML "
            "(e.g. 'config/ml/hyperparams.yml'). "
            "Loaded by HyperparamConfig and delivered to nodes via ml_context.hyperparams_config."
        ),
    )

    mlops_enabled: Optional[bool] = Field(
        default=None,
        description=(
            "Enable MLOps tracking/registry/experiment-tracking integration. "
            "Accepts a real boolean; strings are coerced (true/false/yes/no/1/0). "
            "Unset (the default) means 'decide per pipeline': tracking is wired "
            "up for pipelines that contain ML nodes and skipped for those that "
            "do not. Set it explicitly to force tracking on or off everywhere. "
            "None rather than True on purpose — model_dump(exclude_none=True) "
            "keeps a default but drops a None, so a True default here would "
            "reach the engine indistinguishable from a value the user typed, "
            "and every plain batch pipeline would be tracked as if asked for."
        ),
    )

    split_enforcement: Literal["error", "warn"] = Field(
        default="error",
        description=(
            "What happens when a node bound to a declared train/test split (its own "
            "`split:`, or the pipeline's for an `ml_stage: training`/`evaluation` node) "
            "finishes without applying it through ducta.mlrun.split_dataframe: 'error' "
            "fails the node before its output is written (default); 'warn' logs it. "
            "Either way the run certificate records whether the split was applied."
        ),
    )
    mlops_required: bool = Field(
        default=False,
        description=(
            "If True, abort the pipeline if MLOps initialization fails (hard-fail). "
            "If False, silently fall back to standard execution (soft-fail). "
            "Set to True in production environments to prevent silent loss of experiment tracking."
        ),
    )

    # Default data validation for ML pipelines
    ml_default_sanity_checks: bool = Field(
        default=True,
        description=(
            "Apply a minimal sanity-check floor (empty_dataset) to nodes of type: ml "
            "pipelines that declare no sanity_checks block. Per-node opt-out: "
            "sanity_checks: {enabled: false}"
        ),
    )

    @field_validator("input_path", "output_path", "run_certificate_dir", mode="before")
    @classmethod
    def validate_paths(cls, v: Any) -> str:
        """Validate paths are non-empty strings."""
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Path must be a non-empty string")
        return v

    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
        extra="allow",
    )


class QualityCheckEntrySchema(BaseModel):
    """Schema for a single quality check."""

    enabled: bool = Field(default=True, description="Whether this check is active")
    type: Optional[str] = Field(
        default=None,
        description=(
            "Registry key of the check class when the entry name is a custom label. "
            "Allows multiple instances of the same check type in a single node."
        ),
    )

    model_config = ConfigDict(extra="allow")


class QualityProfileSchema(BaseModel):
    """Schema for a named quality profile entry."""

    checks: Dict[str, Any] = Field(
        default_factory=dict,
        description="Default check configurations for this profile",
    )

    model_config = ConfigDict(extra="allow")


class QualityOutputSchema(BaseModel):
    """Schema for quality report persistence configuration."""

    enabled: bool = Field(
        default=False,
        description="Whether to persist quality reports to storage",
    )
    format: str = Field(
        default="parquet",
        description="Output format: parquet, delta, json, csv",
    )
    write_mode: str = Field(
        default="overwrite",
        description="Write mode: overwrite, append, ignore, error, merge",
    )
    partition_by: Optional[List[str]] = Field(
        default=None,
        description="Partition columns for Parquet/Delta (e.g. ['run_id', 'severity'])",
    )
    schema_def: Optional[str] = Field(
        default=None,
        description="Optional schema definition (DDL or identifier)",
    )
    per_node: bool = Field(
        default=True,
        description="If True, save one report per node; if False, combine all children",
    )
    global_summary: bool = Field(
        default=False,
        description="If True, append node report to global quality summary at pipeline end",
    )

    model_config = ConfigDict(extra="allow")


class QualityGateSchema(BaseModel):
    """Schema for a Quality Gate configuration block."""

    name: str = Field(
        default="quality_gate",
        description="Human-readable identifier for this gate",
    )
    max_errors: int = Field(
        default=0,
        ge=0,
        description="Maximum number of ERROR-level check failures (→BLOCK if exceeded)",
    )
    max_warnings: int = Field(
        default=-1,
        ge=-1,
        description="Maximum WARNING-level failures; -1 = unlimited (→WARN if exceeded)",
    )
    min_pass_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum fraction of checks that must pass (→BLOCK if below); "
            "0.0 (the default) disables the rule. Off by default on purpose: the "
            "pass rate counts every failed check regardless of severity, so any "
            "non-zero default contradicts 'max_warnings: -1' sitting next to it "
            "and blocks on the very warnings that key declares tolerable. This "
            "must stay in step with QualityGateEvaluator.from_config, which "
            "reads the same key with the same default — a node's gate config "
            "reaches it through model_dump(exclude_none=True), which keeps "
            "defaults, so a default written here is a value the evaluator acts "
            "on exactly as if the user had typed it."
        ),
    )
    required_checks: List[str] = Field(
        default_factory=list,
        description="Check names that must pass; any failure/absence → BLOCK",
    )
    score_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Weighted quality score minimum (→BLOCK if below); 0.0 disables",
    )
    score_weights: Dict[str, float] = Field(
        default_factory=dict,
        description="Per-check weights used to compute the quality score",
    )
    consume_from: Optional[str] = Field(
        default=None,
        description=(
            "Source of quality reports for gate evaluation: 'memory' (realtime) "
            "or 'persisted' (from storage). If None, falls back to memory."
        ),
    )
    behavior: str = Field(
        default="skip_downstream",
        description=(
            "Gate action behavior: 'skip_downstream' (mark descendants, continue siblings), "
            "'stop_all' (halt pipeline), or 'warn_only' (log but continue)"
        ),
    )
    output: Optional[QualityOutputSchema] = Field(
        default=None,
        description="Gate result persistence configuration (for audit trail)",
    )

    model_config = ConfigDict(extra="allow")


class QualityGlobalConfig(BaseModel):
    """Quality module configuration block inside ``global_config``."""

    extensions: List[str] = Field(
        default_factory=list,
        description=(
            "Fully-qualified Python module paths whose ``@register_check`` classes "
            "should be auto-loaded at startup.  Example: 'src.checks.my_checks'."
        ),
    )
    profiles: Dict[str, QualityProfileSchema] = Field(
        default_factory=dict,
        description="Named quality profiles reusable across nodes.",
    )
    gate: Optional[QualityGateSchema] = Field(
        default=None,
        description=(
            "Default Quality Gate applied to all nodes. "
            "Can be overridden per-node via data_quality.quality_gate."
        ),
    )

    model_config = ConfigDict(extra="allow")


GlobalConfigSchema.model_rebuild()


class SanityChecksSchema(BaseModel):
    """Schema for node-level ``sanity_checks`` configuration block."""

    inputs: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Per-dataset contracts: {dataset: {checks, gate, fail_fast, ...}}. Each "
            "input the node reads is validated against its own block (format 2 "
            "compiles catalog 'checks' and node 'input_checks' to this)."
        ),
    )
    enabled: bool = Field(
        default=True, description="Whether sanity checks are active for this node"
    )
    fail_fast: bool = Field(
        default=True,
        description="If True, raise on first failed check; if False, collect all failures",
    )
    input_index: int = Field(
        default=0,
        ge=0,
        description="Index of the input DataFrame to check (0 = first input)",
    )
    profile: Optional[str] = Field(
        default=None,
        description=(
            "Name of a quality profile from ``global_config.quality.profiles``. "
            "Profile defaults are merged with node-level ``checks``; node always wins."
        ),
    )
    checks: Dict[str, QualityCheckEntrySchema] = Field(
        default_factory=dict,
        description="Map of check name → check config (e.g. empty_dataset, null_rate, schema)",
    )
    sanity_gate: Optional[QualityGateSchema] = Field(
        default=None,
        description=(
            "Pre-execution Quality Gate configuration. "
            "When set, overrides (merges with) the global quality.gate default. "
            "Node-level values always win."
        ),
    )
    output: Optional[QualityOutputSchema] = Field(
        default=None,
        description="Sanity check report persistence configuration",
    )

    model_config = ConfigDict(extra="allow")


class DataQualitySchema(BaseModel):
    """Schema for node-level ``data_quality`` configuration block."""

    enabled: bool = Field(default=True, description="Whether DQ checks are active for this node")
    fail_fast: bool = Field(
        default=False,
        description="If True, raise immediately on first ERROR check; collect otherwise",
    )
    dataset_name: Optional[str] = Field(
        default=None,
        description="Name under which baseline/history are stored. Defaults to node name.",
    )
    run_id: Optional[str] = Field(
        default=None,
        description="Optional run identifier for report storage (auto-generated if omitted)",
    )
    profile: Optional[str] = Field(
        default=None,
        description=(
            "Name of a quality profile from ``global_config.quality.profiles``. "
            "Profile defaults are merged with node-level ``checks``; node always wins."
        ),
    )
    checks: Dict[str, QualityCheckEntrySchema] = Field(
        default_factory=dict,
        description=(
            "Map of check name → check config. "
            "Supported: null_rate, schema, row_count, duplicates, range, "
            "referential_integrity, anomaly_detection, incremental_volume, "
            "freshness, drift_detection, statistical, cross_table_referential, "
            "dataset_completeness, business_rules, empty_dataset, prediction_rate, "
            "prediction_contract, prediction_drift, or any custom check"
        ),
    )
    quality_gate: Optional[QualityGateSchema] = Field(
        default=None,
        description=(
            "Per-node Quality Gate configuration. "
            "When set, overrides (merges with) the global quality.gate default. "
            "Node-level values always win."
        ),
    )
    output: Optional[QualityOutputSchema] = Field(
        default=None,
        description="Data quality check report persistence configuration",
    )

    model_config = ConfigDict(extra="allow")


class NodeSchema(BaseModel):
    """Validated node configuration."""

    module: Optional[str] = Field(default=None, description="Python module containing the function")
    function: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None,
        description="Python function to execute (string) or streaming function spec (dict)",
    )
    input: Union[List[str], Dict[str, Any]] = Field(
        default_factory=list,
        description="Input data source references or inline streaming input config",
    )
    output: Union[List[str], Dict[str, Any]] = Field(
        default_factory=list,
        description="Output destination references or inline streaming output config",
    )
    dependencies: List[str] = Field(default_factory=list, description="Names of dependent nodes")
    retry: int = Field(default=0, ge=0, le=10, description="Number of retry attempts (0-10)")
    timeout: Optional[int] = Field(
        default=None, ge=1, le=86400, description="Execution timeout in seconds"
    )
    description: Optional[str] = Field(default=None, description="Human-readable description")
    sanity_checks: Optional["SanityChecksSchema"] = Field(
        default=None,
        description="Pre-execution sanity check configuration (fail-fast pattern)",
    )
    data_quality: Optional["DataQualitySchema"] = Field(
        default=None,
        description="Post-execution data quality check configuration",
    )
    ml_stage: Optional[MLStage] = Field(
        default=None,
        description=(
            "Explicit ML lifecycle stage. When set, this node participates in ML "
            "tracking regardless of the pipeline-level is_ml_layer flag. "
            "Valid values: feature_engineering, training, evaluation, serving."
        ),
    )
    run_in_process: bool = Field(
        default=False,
        description=(
            "Run this node in its own process instead of on the shared thread pool. "
            "Worth it only for nodes whose work is pure-Python compute, which holds "
            "the GIL and makes concurrent sibling nodes take turns; nodes dominated "
            "by I/O or by numpy/pandas/sklearn (which release the GIL) gain nothing "
            "and pay the subprocess startup cost. Note that in-memory handoff does "
            "not span processes: a node running this way reads and writes through "
            "storage."
        ),
    )

    @model_validator(mode="after")
    def validate_module_function_path(self) -> "NodeSchema":
        """For batch/ML nodes: ensure the function string is syntactically addressable."""
        if isinstance(self.function, str) and not self.module and "." not in self.function:
            raise ValueError(
                f"Node function '{self.function}' is not addressable: either provide "
                "'module' separately or use a fully-qualified dotted path "
                "(e.g. 'my_package.module.my_func').  Note: this check is syntactic only "
                "— the function is not imported at validation time."
            )
        return self

    model_config = ConfigDict(
        validate_assignment=True,
        extra="allow",
    )


class SplitConfig(BaseModel):
    """Declarative train/test split for ML pipelines."""

    method: Literal["random", "stratified", "temporal", "group"] = Field(
        default="random", description="Split strategy"
    )
    test_size: float = Field(
        default=0.2, gt=0, lt=1, description="Test fraction (0 < test_size < 1)"
    )
    val_size: Optional[float] = Field(
        default=None,
        gt=0,
        lt=1,
        description="Optional validation fraction (of the total). If None, no validation set.",
    )
    stratify_col: Optional[str] = Field(
        default=None,
        description="Column to stratify by (REQUIRED for method=stratified). Must be target class label.",
    )
    time_col: Optional[str] = Field(
        default=None,
        description="Timestamp column for temporal cut (REQUIRED for method=temporal). Rows sorted by this column; train={t <= cutoff}, test={t > cutoff}.",
    )
    group_col: Optional[str] = Field(
        default=None,
        description="Entity column kept intact across sides (REQUIRED for method=group). Each group appears in exactly one of train/test, not both.",
    )
    seed: Optional[int] = Field(
        default=None,
        description="Split seed for reproducibility. If None, falls back to global_config.random_seed. Set explicitly for CV reproducibility.",
    )

    @model_validator(mode="after")
    def validate_method_columns(self) -> "SplitConfig":
        """Each method must declare the column it depends on."""
        required_col = {
            "stratified": ("stratify_col", self.stratify_col),
            "temporal": ("time_col", self.time_col),
            "group": ("group_col", self.group_col),
        }.get(self.method)
        if required_col and not required_col[1]:
            raise ValueError(f"split.method='{self.method}' requires '{required_col[0]}'")
        if self.val_size is not None and self.val_size + self.test_size >= 1:
            raise ValueError("val_size + test_size must be < 1")
        return self

    model_config = ConfigDict(validate_assignment=True)


class PipelineSchema(BaseModel):
    """Validated pipeline configuration."""

    type: PipelineType = Field(
        default=PipelineType.BATCH, description="Pipeline type: batch, ml, streaming, or hybrid"
    )
    nodes: List[str] = Field(
        ..., min_length=1, description="List of node names to execute in order"
    )
    inputs: List[str] = Field(
        default_factory=list, description="Pipeline-level input data source references"
    )
    outputs: List[str] = Field(
        default_factory=list, description="Pipeline-level output destination references"
    )
    description: Optional[str] = Field(default=None, description="Human-readable description")
    requires_dates: bool = Field(
        default=True, description="Whether pipeline requires date parameters"
    )
    spark_config: Optional[Dict[str, Any]] = Field(
        default=None, description="Pipeline-specific Spark configuration"
    )
    hyperparams: Optional[Dict[str, Any]] = Field(
        default=None, description="ML pipeline hyperparameters"
    )
    hyperparams_config: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None,
        description=(
            "Hyperparameter search configuration for this pipeline. "
            "String: key name inside the file at global_config.hyperparams_config_path. "
            "Dict: {path, key} to specify an explicit file path and key."
        ),
    )
    split: Optional[SplitConfig] = Field(
        default=None,
        description="Declarative train/test split, delivered to nodes via ml_context['split']",
    )
    model_version: Optional[str] = Field(
        default=None, description="Override default model version for ML pipelines"
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description=(
            "Pipeline names that must complete successfully before this pipeline runs. "
            "When set, 'ducta start --pipeline <name>' executes the full ancestor chain first."
        ),
    )
    reuse_if_materialized: Optional[bool] = Field(
        default=None,
        description=(
            "Per-pipeline override for chain reuse. true: reuse when outputs exist "
            "even if the global default is off. false: always re-run this pipeline "
            "(e.g. ingestion that must refresh), overriding --reuse-upstream. "
            "None: follow the global [chain].reuse_materialized setting."
        ),
    )

    model_config = ConfigDict(
        validate_assignment=True,
    )


class InputSchema(BaseModel):
    """Validated input configuration."""

    model_config = ConfigDict(
        validate_assignment=True,
        populate_by_name=True,
        extra="allow",
    )

    format: InputFormat = Field(
        ..., description="Input format: parquet, delta, csv, json, kafka, kinesis"
    )
    filepath: Optional[str] = Field(
        default=None, description="Path to input data (supports ${VAR} interpolation)"
    )
    schema_def: Optional[str] = Field(
        default=None, alias="schema", description="Schema definition (DDL or Pydantic schema)"
    )
    options: Optional[Dict[str, Any]] = Field(default=None, description="Format-specific options")
    incremental: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "{column: <date column>}: read only rows with column BETWEEN the run's "
            "start_date and end_date (pushed down to the source), and fingerprint "
            "only that window"
        ),
    )


class OutputSchema(BaseModel):
    """Validated output configuration."""

    model_config = ConfigDict(
        validate_assignment=True,
        populate_by_name=True,
        extra="allow",
    )

    format: OutputFormat = Field(..., description="Output format: parquet, delta, csv, json, kafka")
    filepath: Optional[str] = Field(
        default=None, description="Path to output data (supports ${VAR} interpolation)"
    )
    # No default here: an unset mode is left out of the validated document so
    # the writer's own default (overwrite) applies — injecting a value made
    # every dataset without an explicit mode append on each run.
    write_mode: Optional[WriteMode] = Field(
        default=None,
        description="Write mode: overwrite (default), append, ignore, error, merge",
    )
    options: Optional[Dict[str, Any]] = Field(default=None, description="Format-specific options")
    schema_def: Optional[str] = Field(
        default=None, alias="schema", description="Schema definition (DDL or Pydantic schema)"
    )


class ConfigSchema(BaseModel):
    """Complete configuration schema with validation."""

    global_config: GlobalConfigSchema
    pipelines_config: Dict[str, PipelineSchema]
    nodes_config: Dict[str, NodeSchema]
    input_config: Dict[str, InputSchema]
    output_config: Dict[str, OutputSchema]

    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    def to_dicts(self) -> Dict[str, Any]:
        """Convert validated schema back to plain dictionaries."""
        return {
            "global_config": self.global_config.model_dump(exclude_none=True),
            "pipelines_config": {
                k: v.model_dump(exclude_none=True) for k, v in self.pipelines_config.items()
            },
            "nodes_config": {
                k: v.model_dump(exclude_none=True) for k, v in self.nodes_config.items()
            },
            "input_config": {
                k: v.model_dump(by_alias=True, exclude_none=True)
                for k, v in self.input_config.items()
            },
            "output_config": {
                k: v.model_dump(by_alias=True, exclude_none=True)
                for k, v in self.output_config.items()
            },
        }
