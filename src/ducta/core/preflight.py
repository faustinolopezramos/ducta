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

import difflib
import inspect
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from loguru import logger  # type: ignore

from ducta.core.pipeline_validator import PipelineValidator
from ducta.core.split_validator import SplitValidationError, validate_split_config
from ducta.core.utils import extract_pipeline_nodes, get_node_dependencies
from ducta.gate.validators import ConfigValidator

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


def _check_ml_contract(
    report: PreflightReport,
    context: Any,
    pipeline_name: str,
    pipeline_split: Any,
    node_configs: Dict[str, Dict[str, Any]],
    loader: Any,
) -> None:
    """A declared split must have a node bound to apply it, and that node must be able to.

    Both are known before any data is read: who is bound comes from `ml_stage` and
    `split`, and whether the function can receive `ml_context` from its signature.
    Under `split_enforcement: warn` they are warnings; otherwise errors, because the run
    would fail on them anyway — after the nodes before had already done their work.
    """
    from ducta.core.commands import _accepts_ml_context
    from ducta.core.ml_contract import describe_split, must_apply_split, node_split
    from ducta.core.settings import CoreSettings

    flag = (
        report.warn
        if CoreSettings.from_context(context).split_enforcement == "warn"
        else report.error
    )

    for name, cfg in node_configs.items():
        own = node_split(cfg)
        if own:
            try:
                validate_split_config(own)
            except SplitValidationError as e:
                report.error(f"Node '{name}': invalid split config — {e}")

    if pipeline_split and not any(
        must_apply_split(cfg, pipeline_split) and not node_split(cfg)
        for cfg in node_configs.values()
    ):
        flag(
            f"Pipeline '{pipeline_name}' declares a split ({describe_split(pipeline_split)}) but "
            "no node is bound to apply it, so nothing guarantees the model is fitted and scored "
            "on it. Mark the node that trains with `ml_stage: training` (or `evaluation`), or "
            "move the split onto that node."
        )

    for name, cfg in node_configs.items():
        if (
            _is_streaming_node(cfg)
            or _is_ingestion_node(cfg)
            or not must_apply_split(cfg, pipeline_split)
        ):
            continue
        try:
            func = loader.load({**cfg, "name": name})
            accepts = _accepts_ml_context(func)
        except Exception:  # noqa: BLE001 — an unloadable function is reported elsewhere
            continue
        if not accepts:
            flag(
                f"Node '{name}' must apply a train/test split, but its function takes no "
                "`ml_context`, so it can never receive it. Add `ml_context=None` to its "
                "parameters and call `split_dataframe(df, ml_context.split, ml_context=ml_context)`."
            )


def _check_hyperparams_config(
    report: PreflightReport, context: Any, pipeline_name: str, raw_pipeline: Any
) -> None:
    """``hyperparams_config`` names a search, it does not contain one.

    It is a key in the search file (``hyperparams_config_path``), or ``{path, key}`` to
    point at another file. A mapping holding the search itself (``algorithm``,
    ``search_space``...) used to pass validation and then be ignored by ``--search``.
    """
    declared = raw_pipeline.get("hyperparams_config") if isinstance(raw_pipeline, dict) else None
    if declared is None:
        return
    where = f"Pipeline '{pipeline_name}': hyperparams_config"
    default_path = (getattr(context, "global_config", {}) or {}).get("hyperparams_config_path")
    path: Any
    key: Any

    if isinstance(declared, str):
        path, key = default_path, declared
        if not path:
            report.error(
                f"{where} names the key '{declared}' in the search file, but no file is set. "
                "Add `hyperparams_config_path: <file>` to the project settings, or write "
                "`hyperparams_config: {path: <file>, key: <key>}`."
            )
            return
    elif isinstance(declared, dict):
        extra = sorted(set(declared) - {"path", "key"})
        path, key = declared.get("path", default_path), declared.get("key")
        if extra or not key or not path:
            held = f" (it holds {', '.join(extra)})" if extra else ""
            report.error(
                f"{where} is a mapping{held}, but a mapping is only {{path, key}}: which file "
                "and which key in it. The search itself (algorithm, search_space, objective) "
                "goes in that file, under the key, and the pipeline names it: "
                "`hyperparams_config: <key>` with `hyperparams_config_path` set."
            )
            return
    else:
        report.error(f"{where} must be a key name or {{path, key}}, got {type(declared).__name__}.")
        return

    from pathlib import Path

    from ducta.mlrun.hyperparams import load_hyperparams_config

    if not Path(str(path)).is_file():
        report.error(f"{where} '{key}': the search file {path} does not exist.")
        return
    try:
        loaded = load_hyperparams_config(str(path), pipeline_key=str(key))
    except Exception as e:  # noqa: BLE001 — whatever stops it loading stops the run too
        report.error(f"{where} '{key}' cannot be loaded from {path}: {e}")
        return
    if loaded is None:  # the loader answers a missing key with None and a warning
        report.error(f"{where} '{key}' is not a key of {path}.")


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
    incremental = node_config.get("incremental")
    if incremental is not None:
        column = incremental.get("column") if isinstance(incremental, dict) else None
        if not column or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", str(column)
        ):
            report.error(
                f"Node '{node_name}': ingest.incremental needs a 'column' that is a plain "
                f"column name, got {column!r}."
            )


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


def _check_input_names(
    report: PreflightReport,
    node_name: str,
    node_config: Dict[str, Any],
    sig: inspect.Signature,
    origin: str,
) -> None:
    """``inputs: {param: dataset}`` binds by keyword: each key must be a parameter.

    Left unchecked, a misspelt key fails only when the node runs — after every node
    before it has already written its output.
    """
    named = node_config.get("input")
    if not isinstance(named, dict) or not named or _accepts_var_keyword(sig):
        return
    accepted = [
        name
        for name, p in sig.parameters.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and name not in _INJECTED_KWARGS
    ]
    for key in named:
        if str(key) in sig.parameters:
            continue
        close = difflib.get_close_matches(str(key), accepted, n=1, cutoff=0.5)
        hint = f" — did you mean '{close[0]}'?" if close else ""
        report.error(
            f"Node '{node_name}': inputs key '{key}' is not a parameter of {origin}"
            f"({', '.join(accepted) or 'no inputs'}){hint}. The node would fail when it runs."
        )


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

    module = node_config.get("module")
    function = node_config.get("function")
    origin = f"{module}.{function}" if module and function else node_name

    _check_input_names(report, node_name, node_config, sig, origin)

    if _accepts_var_keyword(sig):
        return

    # The run window (start_date/end_date) is passed only to functions that
    # declare it, so a function without it is fine even when dates are required.

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

        declared = (output_config.get(key) or {}).get("filepath")
        try:
            validator.validate_output_key(key)
        except Exception as e:  # noqa: BLE001 — ConfigurationError → finding
            if not declared:
                # Only a key with no explicit filepath needs the three-part
                # shape: it is what the path is derived from.
                report.error(
                    f"Node '{node_name}': invalid output key '{key}' — {e}. Give it an "
                    "explicit 'filepath', or use a schema.sub_folder.table key."
                )


_EXTRA_NODE_KEYS = frozenset(
    {
        "name",  # stamped on by the config loader
        "type",  # dispatch: batch | streaming | ingestion
        "streaming",  # stream.query_manager (inline connector config)
        "quarantine",  # stream.micro_batch (reject_when / path)
        "depends_on",  # stream.pipeline_manager._process_pipeline_nodes
        "table",  # core.execution.ingestion
        "query",  # core.execution.ingestion
        "source",  # core.execution.ingestion (required by _check_ingestion_node)
        "sources",  # core.execution.ingestion._resolve_sources_path
        "columns",  # core.execution.ingestion._build_dbtable
        "where",  # core.execution.ingestion._build_dbtable
        "incremental",  # core.execution.ingestion (the run's window on one column)
        "options",  # ingestion JDBC options / inline connector options
        "on_missing_input",  # gate.input.InputLoader.load_inputs
        "fail_fast",  # gate.input.InputLoader.load_inputs
        "split",  # core.executors.base._get_pipeline_split_config
        "hyperparams",  # core.commands.MLNodeCommand
        "model_version",  # core.execution.output.OutputWriter.save
        "model",  # core.execution.ml_builder.MLContextBuilder.serving_model
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
    # Dataset contracts: sanity_checks.inputs.<dataset> is a block of its own,
    # whose gate is `gate`.
    contracts = (node_config.get("sanity_checks") or {}).get("inputs")
    if isinstance(contracts, dict):
        for dataset, block in contracts.items():
            if isinstance(block, dict):
                blocks.append((f"sanity_checks.inputs.{dataset}", block))
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


def _check_use_pandas(
    report: PreflightReport,
    node_name: str,
    node_config: Dict[str, Any],
    input_config: Dict[str, Any],
) -> None:
    """``use_pandas`` only changes how a pickle is read. On any other format it was
    accepted and silently ignored: the node got a Spark DataFrame anyway."""
    if _is_streaming_node(node_config):
        return  # a stream node's `input` is its source spec, not catalog datasets
    for key in _input_keys(node_config):
        if not isinstance(key, str):
            continue
        entry = input_config.get(key) or {}
        if not entry.get("use_pandas"):
            continue
        fmt = entry.get("format")
        fmt = str(getattr(fmt, "value", fmt) or "").lower()
        if fmt in ("pickle", "pkl"):
            continue
        report.warn(
            f"Node '{node_name}': input '{key}' sets use_pandas, which applies only to "
            f"pickle datasets — this {fmt or 'dataset'} still arrives as a Spark DataFrame. "
            "For pandas, set `execution_mode: vectorized` on the node."
        )


def _check_stream_quality(
    report: PreflightReport, node_name: str, node_config: Dict[str, Any]
) -> None:
    """A stream node's ``quality`` block runs on every micro-batch (ducta.stream.
    micro_batch), but input contracts (``sanity_checks``) do not: a stream reads an
    inline source, not catalog datasets. Said, instead of accepted and ignored."""
    if not _is_streaming_node(node_config):
        return
    if node_config.get("sanity_checks"):
        report.warn(
            f"Node '{node_name}': input contracts do not run on stream nodes — this "
            "block is not evaluated. Put the checks in the node's own 'quality:' block, "
            "which runs on every batch."
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


#: Keys whose value is a location: a leftover placeholder there is a path nobody can read.
_LOCATION_KEYS = frozenset({"path", "filepath", "checkpointLocation", "checkpoint_location"})
_PLACEHOLDER = re.compile(r"\$\{[^}]*\}")


def _unresolved_placeholders(value: Any, where: str) -> List[Tuple[str, str, str]]:
    """``(location_key_or_empty, dotted_key, placeholder)`` for every ``${...}`` left in *value*."""
    found: List[Tuple[str, str, str]] = []
    if isinstance(value, str):
        key = where.rsplit(".", 1)[-1]
        for match in _PLACEHOLDER.finditer(value):
            found.append((key if key in _LOCATION_KEYS else "", where, match.group(0)))
    elif isinstance(value, dict):
        for k, v in value.items():
            found += _unresolved_placeholders(v, f"{where}.{k}" if where else str(k))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            found += _unresolved_placeholders(v, f"{where}[{i}]")
    return found


def _check_unresolved_placeholders(
    report: PreflightReport,
    node_name: str,
    node_config: Dict[str, Any],
    input_config: Dict[str, Any],
    output_config: Dict[str, Any],
) -> None:
    """A ``${paths.inpt}`` that no variable defines stays in the path as written.

    Nothing flagged it: ``check`` passed, and the run said "skipped for missing
    inputs" without naming the path. In a location (``path``, ``filepath``,
    checkpoints) it is an error; elsewhere (an option, a query) it may be meant
    literally, so it is a warning.
    """
    sources: List[Tuple[str, Any]] = [
        # A stream node's `input`/`output` are inline endpoint dicts, not catalog
        # keys: only a string can name a dataset (the inline blocks are scanned below).
        *((key, input_config.get(key)) for key in _input_keys(node_config) if isinstance(key, str)),
        *(
            (key, output_config.get(key))
            for key in _output_keys(node_config)
            if isinstance(key, str)
        ),
    ]
    for stream_key in ("stream", "streaming"):
        inline = node_config.get(stream_key)
        if isinstance(inline, dict):
            sources.append((f"{stream_key} of node '{node_name}'", inline))
    seen = set()
    for label, config in sources:
        for location, dotted, placeholder in _unresolved_placeholders(config, ""):
            if (label, dotted) in seen:
                continue
            seen.add((label, dotted))
            message = (
                f"Node '{node_name}': '{label}' has {placeholder} in {dotted}, which no "
                "variable defines (a typo in its name? `ducta config show` lists the values)"
            )
            (report.error if location else report.warn)(message)


def _check_quality_config(
    report: PreflightReport, node_name: str, node_config: Dict[str, Any]
) -> None:
    """Validate a node's quality blocks: check names, check parameters, gate behavior."""
    for block_name, block in _quality_blocks(node_config):
        where = f"Node '{node_name}'.{block_name}"
        _check_check_entries(report, where, block.get("checks") or {})
        gate = block.get("gate") if block_name.startswith("sanity_checks.inputs.") else None
        _check_quality_gate(report, where, gate or block.get("quality_gate"))


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


def _check_serving_models(
    report: PreflightReport, context: Any, node_configs: Dict[str, Dict[str, Any]]
) -> None:
    """A node's ``model:`` is well formed, and the registry can name the version it means.

    Resolution reads metadata only — nothing is downloaded or loaded. A model that
    is not there yet is a warning, not an error: a chain may register it in an
    earlier pipeline of the same run.
    """
    from ducta.mlrun.serving import (
        ServingError,
        mlflow_client_from_context,
        pinned_ref,
        resolve_model,
        serving_registry,
    )
    from ducta.setting.project.schema import ModelRef

    registry: Any = None
    for name, cfg in node_configs.items():
        raw = cfg.get("model")
        if not raw:
            continue
        try:
            ref = pinned_ref(ModelRef.model_validate(raw), getattr(context, "pinned_models", None))
        except Exception as e:  # noqa: BLE001 — pydantic's message names the field
            report.error(f"Node '{name}': invalid model — {e}")
            continue
        try:
            if ref.source == "ducta" and registry is None:
                registry = serving_registry(context)
            resolved = resolve_model(
                ref,
                registry=registry,
                mlflow_client=mlflow_client_from_context(context)
                if ref.source == "mlflow"
                else None,
            )
        except ServingError as e:
            report.warn(f"Node '{name}': {e}")
        except Exception as e:  # noqa: BLE001 — an unreachable registry must not crash preflight
            report.warn(f"Node '{name}': could not check model '{ref.name or ref.uri}' — {e}")
        else:
            logger.debug("Node '{}' will serve '{}' v{}", name, resolved.name, resolved.version)


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


def _written_paths(context: Any, node_configs: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    """Where the batch outputs of these nodes land: ``{normalized path: [dataset, ...]}``.

    An output that cannot be resolved is left out: ``_check_io_keys`` reports it.
    """
    from ducta.core.settings import CoreSettings
    from ducta.gate.output.paths import _PathManager

    output_config = getattr(context, "output_config", {}) or {}
    written: Dict[str, List[str]] = {}
    try:
        paths = _PathManager(context, ConfigValidator())
        env = CoreSettings.from_context(context).env
    except Exception as e:  # noqa: BLE001 — never let a checker crash the preflight
        logger.debug("Shared-output check skipped: {}", e)
        return written
    for node_config in node_configs.values():
        if _is_streaming_node(node_config):
            continue
        for key in _output_keys(node_config):
            entry = output_config.get(key)
            if not isinstance(entry, dict) or entry.get("format") == "unity_catalog":
                continue
            try:
                path = paths.resolve_output_path(entry, key, env)
            except Exception as e:  # noqa: BLE001 — never let a checker crash the preflight
                logger.debug("Could not resolve the path of output '{}': {}", key, e)
                continue
            keys = written.setdefault(os.path.normpath(path), [])
            if key not in keys:
                keys.append(key)
    return written


def _check_shared_output_paths(
    report: PreflightReport,
    context: Any,
    pipeline_name: str,
    node_configs: Dict[str, Dict[str, Any]],
) -> None:
    """Two datasets written to one path replace each other, or collide mid-write.

    Same pipeline: an error, unless both only append (then a warning: appends that run in
    parallel can still collide). Another pipeline: a warning, since they may never run
    together. An input reading another pipeline's output path is fine, and not looked at.
    """
    output_config = getattr(context, "output_config", {}) or {}
    written = _written_paths(context, node_configs)
    for path, keys in written.items():
        if len(keys) < 2:
            continue
        message = f"Datasets {', '.join(sorted(keys))} all write to '{path}'"
        modes = {str(getattr(m, "value", m)) for m in _write_modes(output_config, keys)}
        if modes == {"append"}:
            report.warn(f"{message}: nodes running in parallel can collide. Order them.")
        else:
            report.error(f"{message}: each write would replace or collide with the others.")

    pipelines = getattr(context, "pipelines", {}) or {}
    nodes_config = getattr(context, "nodes_config", {}) or {}
    for other_name, other in pipelines.items():
        if other_name == pipeline_name:
            continue
        try:
            other_nodes = extract_pipeline_nodes(other)
        except Exception as e:  # noqa: BLE001 — that pipeline's own preflight reports it
            logger.debug("Could not read the nodes of pipeline '{}': {}", other_name, e)
            continue
        other_configs = {n: (nodes_config.get(n) or {}) for n in other_nodes}
        for path, other_keys in _written_paths(context, other_configs).items():
            distinct = sorted(set(other_keys) - set(written.get(path, [])))
            if path in written and distinct:
                report.warn(
                    f"Datasets {', '.join(sorted(written[path]))} and {', '.join(distinct)} "
                    f"(pipeline '{other_name}') all write to '{path}'."
                )


def _write_modes(output_config: Dict[str, Any], keys: List[str]) -> List[Any]:
    return [(output_config.get(k) or {}).get("write_mode", "overwrite") for k in keys]


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


def _check_windowed_overwrite(
    report: PreflightReport,
    node_name: str,
    node_config: Dict[str, Any],
    input_config: Dict[str, Any],
    output_config: Dict[str, Any],
) -> None:
    """A node that reads one window and overwrites a partitioned dataset replaces all of it.

    Spark's overwrite is static: it deletes every partition first, so a run for one day of
    a table partitioned by day leaves that day and nothing else. Said before the first run
    rather than found in the data. Silent when the author chose: `partition_overwrite:
    dynamic`, `overwrite_strategy: replaceWhere` or mode `merge`.
    """
    if _is_streaming_node(node_config):
        return
    reads_a_window = bool(node_config.get("incremental")) or any(
        isinstance(key, str) and (input_config.get(key) or {}).get("incremental")
        for key in _input_keys(node_config)
    )
    if not reads_a_window:
        return
    for key in _output_keys(node_config):
        entry = output_config.get(key) or {}
        if not isinstance(entry, dict) or not entry.get("partition"):
            continue
        mode = str(
            getattr(entry.get("write_mode"), "value", entry.get("write_mode")) or "overwrite"
        )
        if mode != "overwrite":
            continue
        if str(entry.get("partition_overwrite") or "").lower() == "dynamic":
            continue
        if str(entry.get("overwrite_strategy") or "").lower() == "replacewhere":
            continue
        report.warn(
            f"Node '{node_name}': output '{key}' is partitioned and overwritten, but the node "
            "reads one window (incremental). Each run replaces the WHOLE dataset, not just "
            "the window it read. Choose: `write.partition_overwrite: dynamic` (parquet, csv, "
            "json, orc), `write.overwrite_strategy: replaceWhere` or `write.mode: merge` "
            "(Delta) to replace only the run's slice, or keep this if replacing everything "
            "is what you want."
        )


def _check_state_dirs(report: PreflightReport, settings: Any) -> None:
    """Ducta's own state directories must be local, except a storage run-lock lease.

    The defaults already stay local under a cloud output (``CoreSettings.state_dir_notes``
    says where); a directory set by hand to cloud storage would be written as a local
    folder named ``s3:``.
    """
    from ducta.gate.constants import is_cloud_path

    for note in settings.state_dir_notes:
        report.warn(note)
    for setting, value in (
        ("run_certificate_dir", settings.run_certificate_dir),
        ("chain.state_dir", settings.chain_state_dir),
    ):
        if is_cloud_path(value):
            report.error(
                f"{setting} is {value}, but it must be a local folder: Ducta writes "
                "it as files. Point it at a local path (or remove it to use the default); "
                "DUCTA_STORAGE_BACKEND keeps a shared copy of the certificates."
            )
    if settings.run_lock_backend == "local" and "://" in settings.run_lock_dir:
        report.error(
            f"run_lock.dir is {settings.run_lock_dir}, but backend 'local' needs a local "
            "folder; use run_lock: {backend: storage} for a lock on object storage."
        )


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
    _check_state_dirs(report, settings)
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
        _check_unresolved_placeholders(
            report, node_name, node_configs[node_name], input_config, output_config
        )
        _check_quality_config(report, node_name, node_configs[node_name])
        _check_use_pandas(report, node_name, node_configs[node_name], input_config)
        _check_stream_quality(report, node_name, node_configs[node_name])
        _check_unknown_node_keys(report, node_name, node_configs[node_name])
        _check_merge_outputs(report, node_name, node_configs[node_name], output_config)
        _check_windowed_overwrite(
            report, node_name, node_configs[node_name], input_config, output_config
        )
    _check_shared_output_paths(report, context, pipeline_name, node_configs)

    _check_profiles(report, context)
    _check_evidence_policy(report, context)

    # From pipelines_config: `context.pipelines` rebuilds each pipeline without its
    # `split`, so reading it there meant this validation never ran.
    raw_pipeline = (getattr(context, "pipelines_config", {}) or {}).get(pipeline_name) or {}
    split_config = (
        raw_pipeline.get("split") if isinstance(raw_pipeline, dict) else None
    ) or pipeline.get("split")
    if split_config is not None and hasattr(split_config, "model_dump"):
        split_config = split_config.model_dump(exclude_none=True)
    if split_config:
        try:
            validate_split_config(split_config)
        except SplitValidationError as e:
            report.error(f"Pipeline '{pipeline_name}': invalid split config — {e}")

    _check_ml_contract(report, context, pipeline_name, split_config, node_configs, loader)
    _check_hyperparams_config(report, context, pipeline_name, raw_pipeline)
    _check_serving_models(report, context, node_configs)

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
