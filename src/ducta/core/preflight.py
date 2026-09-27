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

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Dict, List

from loguru import logger  # type: ignore

from ducta.core.pipeline_validator import PipelineValidator
from ducta.core.split_validator import SplitValidationError, validate_split_config
from ducta.core.utils import extract_pipeline_nodes, get_node_dependencies
from ducta.gate.validators import ConfigValidator

_PREFLIGHT_SPLIT_DATASET_SIZE_SENTINEL = 10_000

_INJECTED_KWARGS = ("start_date", "end_date", "ml_context")


@dataclass
class PreflightReport:
    """Result of validating a single pipeline before execution."""

    pipeline_name: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when there are no blocking errors (warnings are allowed)."""
        return not self.errors

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def _input_keys(node_config: Dict[str, Any]) -> List[str]:
    """Dataset keys a node consumes, whether ``input`` is a list or a {param: key} map."""
    raw = node_config.get("input", []) or []
    if isinstance(raw, dict):
        return list(raw.values())
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def _output_keys(node_config: Dict[str, Any]) -> List[str]:
    """Dataset keys a node produces (``output`` may be a list or a single string)."""
    raw = node_config.get("output", []) or []
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def _is_streaming_node(node_config: Dict[str, Any]) -> bool:
    return node_config.get("type", "").lower() == "streaming" or bool(node_config.get("streaming"))


def _is_ingestion_node(node_config: Dict[str, Any]) -> bool:
    return str(node_config.get("type", "")).lower() == "ingestion"


def _check_ingestion_node(
    report: PreflightReport, node_name: str, node_config: Dict[str, Any]
) -> None:
    """Declarative ingestion nodes have no module.function; validate their own shape."""
    if not node_config.get("source"):
        report.error(
            f"Node '{node_name}': ingestion node requires a 'source' (a connection "
            f"defined in config/sources.yaml)."
        )
    has_table = bool(node_config.get("table"))
    has_query = bool(node_config.get("query"))
    if not has_table and not has_query:
        report.error(f"Node '{node_name}': ingestion node requires 'table' or 'query'.")
    if has_table and has_query:
        report.error(f"Node '{node_name}': ingestion node must set 'table' OR 'query', not both.")


def _accepts_var_keyword(sig: inspect.Signature) -> bool:
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())


def _accepts_var_positional(sig: inspect.Signature) -> bool:
    return any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())


def _positional_input_slots(sig: inspect.Signature) -> int:
    """Count params that can receive a positionally-passed input DataFrame."""
    count = 0
    for name, p in sig.parameters.items():
        if name in _INJECTED_KWARGS:
            continue
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            count += 1
    return count


def _check_node_function(
    report: PreflightReport,
    loader: Any,
    node_name: str,
    node_config: Dict[str, Any],
    requires_dates: bool,
) -> None:
    """Import the node function and verify its signature matches the call convention."""
    if _is_streaming_node(node_config) or _is_ingestion_node(node_config):
        return

    node_with_name = {**node_config, "name": node_name}
    try:
        func = loader.load(node_with_name)
    except Exception as e:
        report.error(f"Node '{node_name}': cannot load function — {e}")
        return

    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return

    if _accepts_var_keyword(sig):
        return

    module = node_config.get("module")
    function = node_config.get("function")
    origin = f"{module}.{function}" if module and function else node_name

    if requires_dates and not _is_streaming_node(node_config):
        for kwarg in ("start_date", "end_date"):
            if kwarg not in sig.parameters:
                report.error(
                    f"Node '{node_name}': function '{origin}' must accept '{kwarg}' "
                    f"(the pipeline requires dates). Add '{kwarg}=None' or **kwargs to its signature."
                )

    n_inputs = len(_input_keys(node_config))
    if n_inputs and not _accepts_var_positional(sig):
        slots = _positional_input_slots(sig)
        if slots < n_inputs:
            report.warn(
                f"Node '{node_name}': function '{origin}' has {slots} positional parameter(s) "
                f"but the node declares {n_inputs} input(s). Inputs are passed positionally in "
                f"declaration order; verify the signature."
            )


def _check_io_keys(
    report: PreflightReport,
    node_name: str,
    node_config: Dict[str, Any],
    input_config: Dict[str, Any],
    output_config: Dict[str, Any],
    validator: ConfigValidator,
) -> None:
    """Every input key must be registered in the input catalog; every output key in the
    output catalog and well-formed as ``schema.sub_folder.table_name`` (batch/ml only)."""
    if _is_streaming_node(node_config):
        return

    for key in _input_keys(node_config):
        if key not in input_config:
            report.error(
                f"Node '{node_name}': input '{key}' is not registered in the input catalog. "
                f"Intermediate datasets consumed downstream must be declared under 'input'. "
                f"If this environment has its own input config, that file replaces the base "
                f"one rather than extending it — declare '{key}' there."
            )

    for key in _output_keys(node_config):
        if key not in output_config:
            report.error(
                f"Node '{node_name}': output '{key}' is not registered in the output catalog. "
                f"If this environment has its own output config, that file replaces the base "
                f"one rather than extending it — declare '{key}' there."
            )
            continue

        try:
            validator.validate_output_key(key)
        except Exception as e:  # noqa: BLE001 — ConfigurationError → finding
            report.error(f"Node '{node_name}': invalid output key '{key}' — {e}")


_EXTRA_NODE_KEYS = frozenset(
    {
        "name",  # stamped on by the config loader
        "type",  # dispatch: batch | streaming | ingestion
        "streaming",  # stream.query_manager (inline connector config)
        "depends_on",  # stream.pipeline_manager._process_pipeline_nodes
        "table",  # core.execution.ingestion
        "query",  # core.execution.ingestion
        "source",  # core.execution.ingestion (required by _check_ingestion_node)
        "sources",  # core.execution.ingestion._resolve_sources_path
        "columns",  # core.execution.ingestion._build_dbtable
        "where",  # core.execution.ingestion._build_dbtable
        "options",  # ingestion JDBC options / inline connector options
        "on_missing_input",  # gate.input.InputLoader.load_inputs
        "fail_fast",  # gate.input.InputLoader.load_inputs
        "split",  # core.executors.base._get_pipeline_split_config
        "hyperparams",  # core.commands.MLNodeCommand
        "model_version",  # core.execution.output.OutputWriter.save
        "execution_mode",  # core.commands (vectorized execution)
        "execution_mode_max_rows",  # core.commands._guarded_to_pandas
        "metrics",  # setting.contexts.MLConfigMixin.get_node_ml_config
        "model_artifacts",  # gate.output.manager._save_model_artifacts
        "mlops_enabled",  # core.mlops_auto_config.should_enable_mlops
        "ml",  # core.mlops_auto_config.resolve_ml_stage (nested `stage`)
    }
)


def _quality_blocks(node_config: Dict[str, Any]) -> List[tuple]:
    """The (block_name, block) quality sections a node may declare."""
    blocks = []
    for key in ("data_quality", "sanity_checks"):
        block = node_config.get(key)
        if isinstance(block, dict):
            blocks.append((key, block))
    return blocks


def _check_check_entries(report: PreflightReport, where: str, checks: Dict[str, Any]) -> None:
    """Validate every check entry's name against the registry, and its parameters."""
    from ducta.check.core import COMMON_CHECK_PARAMS, QUALITY_CHECKS_REGISTRY

    for entry_name, entry in (checks or {}).items():
        entry_dict = entry if isinstance(entry, dict) else {}

        registry_key = entry_dict.get("type") or entry_name
        check_class = QUALITY_CHECKS_REGISTRY.get(registry_key)
        if check_class is None:
            available = ", ".join(sorted(QUALITY_CHECKS_REGISTRY)) or "(none registered)"
            named_by = "type" if entry_dict.get("type") else "entry name"
            report.error(
                f"{where}: check '{registry_key}' (given as the {named_by}) is not a "
                f"registered check. It will fail at runtime as an ERROR-severity result, "
                f"which a quality gate reports as blocked data rather than as this "
                f"configuration mistake. Available: {available}"
            )
            continue

        declared = getattr(check_class, "CONFIG_PARAMS", None)
        if declared is None:
            continue  # a plugin check that has not declared its parameters
        allowed = set(declared) | set(COMMON_CHECK_PARAMS)

        unknown = sorted(k for k in entry_dict if not str(k).startswith("_") and k not in allowed)
        if unknown:
            report.error(
                f"{where}: check '{entry_name}' does not accept {unknown}. Unknown keys are "
                f"silently ignored, so the check runs with its defaults instead of the "
                f"values written here. Accepted: {sorted(allowed)}"
            )


def _check_quality_gate(report: PreflightReport, where: str, gate: Any) -> None:
    """Validate the parts of a quality gate that fall back silently at runtime."""
    if not isinstance(gate, dict):
        return
    raw_behavior = gate.get("behavior")
    if raw_behavior is None:
        return
    from ducta.check.gate import GateBehavior

    aliases = {"block": GateBehavior.STOP_ALL.value, "warn": GateBehavior.WARN_ONLY.value}
    normalized = aliases.get(str(raw_behavior), str(raw_behavior))
    valid = [b.value for b in GateBehavior]
    if normalized not in valid:
        report.error(
            f"{where}: quality gate behavior '{raw_behavior}' is not valid. At runtime this "
            f"falls back to '{GateBehavior.SKIP_DOWNSTREAM.value}', so the gate would not do "
            f"what the config says. Valid: {', '.join(valid)} "
            f"(aliases: {', '.join(sorted(aliases))})"
        )


def _check_quality_config(
    report: PreflightReport, node_name: str, node_config: Dict[str, Any]
) -> None:
    """Validate a node's quality blocks: check names, check parameters, gate behavior."""
    for block_name, block in _quality_blocks(node_config):
        where = f"Node '{node_name}'.{block_name}"
        _check_check_entries(report, where, block.get("checks") or {})
        _check_quality_gate(report, where, block.get("quality_gate"))


_LEGACY_DSTREAM_PREFIX = "spark.streaming."


def _check_streaming_output_format(
    report: PreflightReport, node_name: str, node_config: Dict[str, Any], policy: Any
) -> None:
    """A streaming sink's format must be one the writer can actually build."""
    output_config = node_config.get("output")
    if not isinstance(output_config, dict):
        return
    output_format = output_config.get("format")
    if not output_format:
        return  # absence is already reported by _validate_streaming_requirements
    try:
        if policy.is_supported_output(output_format):
            return
        supported = policy.get_supported_output_formats()
    except Exception as e:  # noqa: BLE001 — a policy that cannot answer blocks nothing
        logger.debug("Streaming output-format check skipped for '{}': {}", node_name, e)
        return
    report.error(
        f"Streaming node '{node_name}' has unsupported streaming output format "
        f"'{output_format}'. Supported: {supported}"
    )


def _check_legacy_dstream_config(report: PreflightReport, where: str, spark_config: Any) -> None:
    """Warn about ``spark.streaming.*`` keys, which Structured Streaming ignores."""
    if not isinstance(spark_config, dict):
        return
    legacy = sorted(k for k in spark_config if str(k).startswith(_LEGACY_DSTREAM_PREFIX))
    if legacy:
        report.warn(
            f"{where}: {legacy} belong to legacy Spark Streaming (DStream) and have no "
            f"effect with Structured Streaming, which is what Ducta runs. Use the "
            f"spark.sql.streaming.* equivalents instead."
        )


def _check_profiles(report: PreflightReport, context: Any) -> None:
    """Validate the shared quality profiles the same way as node-level checks."""
    global_config = getattr(context, "global_config", {}) or {}
    if not isinstance(global_config, dict):
        return
    profiles = ((global_config.get("quality") or {}).get("profiles")) or {}
    if not isinstance(profiles, dict):
        return
    for profile_name, profile in profiles.items():
        if isinstance(profile, dict):
            _check_check_entries(
                report,
                f"Quality profile '{profile_name}'",
                profile.get("checks") or {},
            )


def _check_unknown_node_keys(
    report: PreflightReport, node_name: str, node_config: Dict[str, Any]
) -> None:
    """Warn about node keys nothing reads — a misspelling that changes behaviour."""
    from ducta.setting.schemas import NodeSchema

    known = set(NodeSchema.model_fields) | set(_EXTRA_NODE_KEYS)
    unknown = sorted(k for k in node_config if not str(k).startswith("_") and k not in known)
    if unknown:
        report.warn(
            f"Node '{node_name}': {unknown} are not node configuration keys and are "
            f"ignored. A misspelled key is dropped in silence — `dependencie` instead of "
            f"`dependencies`, say, loses the ordering it was meant to declare. "
            f"Known keys: {sorted(known)}"
        )


def _check_merge_outputs(
    report: PreflightReport,
    node_name: str,
    node_config: Dict[str, Any],
    output_config: Dict[str, Any],
) -> None:
    """``write_mode: merge`` needs Delta and a well-formed ``merge:`` block —
    caught here rather than after the node has computed its whole output."""
    from ducta.gate.exceptions import ConfigurationError as GateConfigurationError
    from ducta.gate.writers import validate_merge_spec

    for key in _output_keys(node_config):
        entry = output_config.get(key) or {}
        if not isinstance(entry, dict) or entry.get("write_mode") != "merge":
            continue
        raw_fmt = entry.get("format", "")
        # Validated configs carry the OutputFormat enum, whose str() is
        # "OutputFormat.DELTA" — compare on its value.
        fmt = str(getattr(raw_fmt, "value", raw_fmt)).lower()
        if fmt != "delta":
            report.error(
                f"Node '{node_name}': output '{key}' uses write_mode 'merge', which is "
                f"supported only for format 'delta' (got '{fmt or '?'}')"
            )
            continue
        try:
            validate_merge_spec(entry.get("merge"))
        except GateConfigurationError as e:
            report.error(f"Node '{node_name}': output '{key}': {e}")


def _check_evidence_policy(report: PreflightReport, context: Any) -> None:
    """Fail before running when the project's evidence policy cannot be met."""
    from ducta.core.settings import EVIDENCE_SIGNED, CoreSettings

    try:
        settings = CoreSettings.from_context(context)
    except Exception as e:  # noqa: BLE001
        logger.debug("Evidence policy check skipped: {}", e)
        return
    for problem in settings.evidence_problems:
        report.error(f"Evidence policy: {problem}")
    if settings.evidence_level == EVIDENCE_SIGNED:
        from ducta.core.certificate import resolve_signing_key

        if resolve_signing_key(context) is None:
            report.error(
                "Evidence policy: evidence_level is 'signed' but no signing key is "
                "configured. Set the DUCTA_CERTIFICATE_KEY environment variable, or "
                "lower evidence_level to 'required'."
            )


def validate_pipeline(context: Any, pipeline_name: str) -> PreflightReport:
    """Validate a single pipeline's configuration without executing it."""
    report = PreflightReport(pipeline_name=pipeline_name)

    pipelines = getattr(context, "pipelines", {}) or {}
    pipeline = pipelines.get(pipeline_name)
    if not pipeline:
        available = ", ".join(sorted(pipelines)) or "(none)"
        report.error(f"Pipeline '{pipeline_name}' not found. Available: {available}")
        return report

    try:
        PipelineValidator.validate_pipeline_config(pipeline)
        pipeline_nodes = extract_pipeline_nodes(pipeline)
    except Exception as e:  # noqa: BLE001
        report.error(f"Pipeline '{pipeline_name}': {e}")
        return report

    nodes_config: Dict[str, Any] = getattr(context, "nodes_config", {}) or {}
    node_configs = {n: (nodes_config.get(n) or {}) for n in pipeline_nodes}

    try:
        PipelineValidator.validate_node_configs(pipeline_nodes, node_configs)
    except Exception as e:  # noqa: BLE001
        report.error(str(e))
        return report  # can't check further without every node config

    try:
        PipelineValidator.validate_no_dag_cycles(pipeline_nodes, node_configs)
    except Exception as e:  # noqa: BLE001
        report.error(f"Dependency cycle: {e}")

    for node_name in pipeline_nodes:
        for dep in get_node_dependencies(node_configs[node_name]):
            if dep not in node_configs:
                report.error(
                    f"Node '{node_name}': dependency '{dep}' is not a node in pipeline "
                    f"'{pipeline_name}'. Node-level 'dependencies' cannot cross pipelines; "
                    f"to order one pipeline after another use pipeline-level 'depends_on' "
                    f"(or just let Ducta infer it from the datasets they share)."
                )

    requires_dates = bool(pipeline.get("requires_dates", True))
    loader = _make_function_loader(context)
    for node_name in pipeline_nodes:
        if _is_ingestion_node(node_configs[node_name]):
            _check_ingestion_node(report, node_name, node_configs[node_name])
        else:
            _check_node_function(report, loader, node_name, node_configs[node_name], requires_dates)

    input_config = getattr(context, "input_config", {}) or {}
    output_config = getattr(context, "output_config", {}) or {}
    validator = ConfigValidator()
    for node_name in pipeline_nodes:
        _check_io_keys(
            report, node_name, node_configs[node_name], input_config, output_config, validator
        )
        _check_quality_config(report, node_name, node_configs[node_name])
        _check_unknown_node_keys(report, node_name, node_configs[node_name])
        _check_merge_outputs(report, node_name, node_configs[node_name], output_config)

    _check_profiles(report, context)
    _check_evidence_policy(report, context)

    split_config = pipeline.get("split")
    if split_config:
        try:
            validate_split_config(split_config, _PREFLIGHT_SPLIT_DATASET_SIZE_SENTINEL)
        except SplitValidationError as e:
            report.error(f"Pipeline '{pipeline_name}': invalid split config — {e}")

    streaming_nodes = [n for n in pipeline_nodes if _is_streaming_node(node_configs[n])]
    if streaming_nodes:
        try:
            from ducta.setting.validators import FormatPolicy

            policy = getattr(context, "format_policy", None) or FormatPolicy()
            for msg in PipelineValidator._validate_streaming_requirements(
                streaming_nodes, node_configs, policy
            ):
                report.error(msg)
            for node_name in streaming_nodes:
                _check_streaming_output_format(report, node_name, node_configs[node_name], policy)
            _check_legacy_dstream_config(
                report, f"Pipeline '{pipeline_name}'", pipeline.get("spark_config")
            )
        except Exception as e:  # noqa: BLE001 — never let a checker crash the preflight
            logger.debug("Streaming requirement check skipped: {}", e)

    return report


def validate_all_pipelines(context: Any) -> Dict[str, PreflightReport]:
    """Validate every pipeline defined in the context."""
    pipelines = getattr(context, "pipelines", {}) or {}
    return {name: validate_pipeline(context, name) for name in pipelines}


def _make_function_loader(context: Any) -> Any:
    """Build a FunctionLoader for import checks; degrade to a no-op if unavailable."""
    from ducta.core.execution.loader import FunctionLoader

    is_ml_layer = bool(getattr(context, "is_ml_layer", False))
    return FunctionLoader(context, is_ml_layer=is_ml_layer)
