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
                f"Intermediate datasets consumed downstream must be declared under 'input'."
            )

    for key in _output_keys(node_config):
        if key not in output_config:
            report.error(
                f"Node '{node_name}': output '{key}' is not registered in the output catalog."
            )
            continue

        try:
            validator.validate_output_key(key)
        except Exception as e:  # noqa: BLE001 — ConfigurationError → finding
            report.error(f"Node '{node_name}': invalid output key '{key}' — {e}")


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
                    f"'{pipeline_name}'."
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
