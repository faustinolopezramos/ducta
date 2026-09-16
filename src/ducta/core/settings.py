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

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from loguru import logger  # type: ignore

from ducta.core.context_utils import get_context_value as _get
from ducta.setting.environments import sanitize_env_for_path
from ducta.setting.interpolator import VariableInterpolator

# Accepted spellings for boolean-ish configuration values.
_TRUE_VALUES = frozenset({"true", "yes", "on", "1"})
_FALSE_VALUES = frozenset({"false", "no", "off", "0", ""})
MAX_TIMEOUT_SECONDS = 86_400

DEFAULT_EXECUTION_TIMEOUT_SECONDS = 3_600
DEFAULT_NODE_TIMEOUT_SECONDS = 1_800
DEFAULT_MAX_PARALLEL_NODES = 4
DEFAULT_MAX_STREAMING_PIPELINES = 5

# Ducta storage convention: every state directory the framework itself writes
# (as opposed to a node's own data output) lives under the environment's data
# tree, scoped by ${output_path}/${environment} exactly like
# global_config.quality.output.base_path already does — see docs/README for
# "Ducta storage convention". Run certificates and chain state hide under a
# `.ducta/` namespace there so they read as framework bookkeeping, not data;
# quality reports stay visible at `${output_path}/${environment}/quality`
# (unchanged) because a project may want to browse/ship those.
DEFAULT_CERTIFICATE_DIR = "${output_path}/${environment}/.ducta/runs"
DEFAULT_CHAIN_STATE_DIR = "${output_path}/${environment}/.ducta/chain_state"

CHAIN_ON_GATE_BLOCKED_STOP = "stop"
CHAIN_ON_GATE_BLOCKED_CONTINUE = "continue"
CHAIN_ON_GATE_BLOCKED_CHOICES = (CHAIN_ON_GATE_BLOCKED_STOP, CHAIN_ON_GATE_BLOCKED_CONTINUE)


def coerce_bool(name: str, raw: Any, *, default: bool) -> bool:
    """Coerce a settings value to ``bool``, warning on anything unrecognized."""
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
        logger.warning(
            "Setting '{}' has unrecognized value {!r}; expected a boolean "
            "(true/false). Falling back to default={}.",
            name,
            raw,
            default,
        )
        return default
    if isinstance(raw, (int, float)):
        return bool(raw)
    logger.warning(
        "Setting '{}' has unexpected type {}; expected a boolean. Falling back to default={}.",
        name,
        type(raw).__name__,
        default,
    )
    return default


def coerce_choice(name: str, raw: Any, *, choices: Tuple[str, ...], default: str) -> str:
    """Coerce a settings value to one of ``choices``, warning on anything else."""
    if raw is None:
        return default
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in choices:
            return normalized
    logger.warning(
        "Setting '{}' has unrecognized value {!r}; expected one of {}. "
        "Falling back to default={!r}.",
        name,
        raw,
        ", ".join(choices),
        default,
    )
    return default


def coerce_int(name: str, raw: Any, *, default: int, minimum: int = 1) -> int:
    """Coerce a settings value to a positive ``int``, warning on bad input."""
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Setting '{}' has non-numeric value {!r}; falling back to default={}.",
            name,
            raw,
            default,
        )
        return default
    if value < minimum:
        logger.warning(
            "Setting '{}' is {} but the minimum is {}; using {}.", name, value, minimum, minimum
        )
        return minimum
    return value


def clamp_timeout(name: str, value: int, *, ceiling: int = MAX_TIMEOUT_SECONDS) -> int:
    """Clamp a timeout to ``ceiling``, logging when the configured value is dropped."""
    if value <= ceiling:
        return value
    logger.warning(
        "Setting '{}' is {}s, above the {}s maximum; using {}s instead.",
        name,
        value,
        ceiling,
        ceiling,
    )
    return ceiling


def _as_mapping(value: Any) -> Dict[str, Any]:
    """Return a plain dict for a settings sub-section, whatever shape it arrived in."""
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:  # noqa: BLE001 - a malformed section must not abort resolution
            return {}
    return {}


@dataclass(frozen=True)
class CoreSettings:
    """Every configuration value ``ducta.core`` consumes, resolved once."""

    # ── Execution ────────────────────────────────────────────────────────────
    max_parallel_nodes: int = DEFAULT_MAX_PARALLEL_NODES
    execution_timeout_seconds: int = DEFAULT_EXECUTION_TIMEOUT_SECONDS
    node_timeout_seconds: int = DEFAULT_NODE_TIMEOUT_SECONDS
    max_streaming_pipelines: int = DEFAULT_MAX_STREAMING_PIPELINES

    # ── Dates ────────────────────────────────────────────────────────────────
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    # ── Environment ──────────────────────────────────────────────────────────
    # Single resolved value. Every core call site that used to re-derive this
    # (with three different precedence orders) now reads this field.
    env: Optional[str] = None
    project_id: Optional[str] = None

    # ── Reproducibility ──────────────────────────────────────────────────────
    random_seed: Optional[int] = None

    # ── Validation / preflight ───────────────────────────────────────────────
    preflight_enabled: bool = True
    ml_default_sanity_checks: bool = True

    # ── Security ─────────────────────────────────────────────────────────────
    strict_module_import: bool = True

    # ── MLOps ────────────────────────────────────────────────────────────────
    mlops_enabled: bool = True
    mlops_required: bool = False
    mlflow_enabled: bool = False
    fingerprint_policy: str = "record"

    # ── Run certificates ─────────────────────────────────────────────────────
    enable_run_certificate: bool = True
    require_run_certificate: bool = False
    run_certificate_dir: str = DEFAULT_CERTIFICATE_DIR
    certificate_signing_key: Optional[str] = None

    # ── Chain reuse ──────────────────────────────────────────────────────────
    chain_reuse_materialized: bool = False
    chain_staleness_check: bool = True
    chain_on_gate_blocked: str = CHAIN_ON_GATE_BLOCKED_STOP
    chain_state_dir: str = DEFAULT_CHAIN_STATE_DIR

    quality: Dict[str, Any] = field(default_factory=dict)
    ingestion: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_context(cls, context: Any) -> "CoreSettings":
        """Resolve settings from a pipeline ``Context`` (or a bare settings dict)."""
        gs = context if isinstance(context, Mapping) else _get(context, "global_config", {})
        gs = _as_mapping(gs)

        execution_timeout = clamp_timeout(
            "execution_timeout_seconds",
            coerce_int(
                "execution_timeout_seconds",
                gs.get("execution_timeout_seconds"),
                default=DEFAULT_EXECUTION_TIMEOUT_SECONDS,
            ),
        )
        node_timeout = clamp_timeout(
            "node_timeout_seconds",
            coerce_int(
                "node_timeout_seconds",
                gs.get("node_timeout_seconds"),
                default=DEFAULT_NODE_TIMEOUT_SECONDS,
            ),
        )

        mlops_section = _as_mapping(gs.get("mlops"))
        mlflow_section = _as_mapping(gs.get("mlflow"))
        chain_section = _as_mapping(gs.get("chain"))
        resolved_env = cls._resolve_env(context, gs)

        return cls(
            max_parallel_nodes=coerce_int(
                "max_parallel_nodes",
                gs.get("max_parallel_nodes"),
                default=DEFAULT_MAX_PARALLEL_NODES,
            ),
            execution_timeout_seconds=execution_timeout,
            node_timeout_seconds=node_timeout,
            max_streaming_pipelines=coerce_int(
                "max_streaming_pipelines",
                gs.get("max_streaming_pipelines"),
                default=DEFAULT_MAX_STREAMING_PIPELINES,
            ),
            start_date=_optional_str(gs.get("start_date")),
            end_date=_optional_str(gs.get("end_date")),
            env=resolved_env,
            project_id=_optional_str(gs.get("project_id")),
            random_seed=_optional_int("random_seed", gs.get("random_seed")),
            preflight_enabled=coerce_bool(
                "preflight_enabled", gs.get("preflight_enabled"), default=True
            ),
            ml_default_sanity_checks=coerce_bool(
                "ml_default_sanity_checks", gs.get("ml_default_sanity_checks"), default=True
            ),
            strict_module_import=coerce_bool(
                "strict_module_import",
                _get(context, "strict_module_import", gs.get("strict_module_import")),
                default=True,
            ),
            mlops_enabled=cls._resolve_mlops_enabled(gs, mlops_section),
            mlops_required=coerce_bool("mlops_required", gs.get("mlops_required"), default=False),
            mlflow_enabled=cls._resolve_mlflow_enabled(mlflow_section),
            fingerprint_policy=str(gs.get("fingerprint_policy") or "record"),
            enable_run_certificate=coerce_bool(
                "enable_run_certificate", gs.get("enable_run_certificate"), default=True
            ),
            require_run_certificate=coerce_bool(
                "require_run_certificate", gs.get("require_run_certificate"), default=False
            ),
            run_certificate_dir=cls._resolve_scoped_dir(
                str(gs.get("run_certificate_dir") or DEFAULT_CERTIFICATE_DIR), gs, resolved_env
            ),
            certificate_signing_key=_optional_str(gs.get("certificate_signing_key")),
            chain_reuse_materialized=coerce_bool(
                "chain.reuse_materialized", chain_section.get("reuse_materialized"), default=False
            ),
            chain_state_dir=cls._resolve_scoped_dir(
                str(chain_section.get("state_dir") or DEFAULT_CHAIN_STATE_DIR), gs, resolved_env
            ),
            chain_staleness_check=coerce_bool(
                "chain.staleness_check", chain_section.get("staleness_check"), default=True
            ),
            chain_on_gate_blocked=coerce_choice(
                "chain.on_gate_blocked",
                chain_section.get("on_gate_blocked"),
                choices=CHAIN_ON_GATE_BLOCKED_CHOICES,
                default=CHAIN_ON_GATE_BLOCKED_STOP,
            ),
            quality=_as_mapping(gs.get("quality")),
            ingestion=_as_mapping(gs.get("ingestion")),
        )

    @staticmethod
    def _resolve_scoped_dir(template: str, gs: Mapping[str, Any], env: Optional[str]) -> str:
        """Resolve a Ducta-managed state-directory template (run certificates,
        chain state) to a concrete, environment-scoped path.

        Interpolates ``${output_path}``/``${environment}`` (and any other
        global_config key) the same way ``quality.output.base_path`` already
        does, so a project that leaves the setting at its default gets
        ``${output_path}/${environment}/.ducta/<kind>`` — next to the
        environment's own data, not the project root (see
        ``DEFAULT_CERTIFICATE_DIR``/``DEFAULT_CHAIN_STATE_DIR``).

        A template that does not itself reference ``${environment}`` (a
        project pointing this at a fixed custom/legacy path) is still
        env-scoped, by appending the sanitized environment as a path segment
        — otherwise two environments would collide in the same directory,
        which is the exact bug this convention exists to avoid.
        """
        safe_env = sanitize_env_for_path(env)
        has_env_placeholder = "${environment}" in template
        resolved = template
        if "${" in template:
            variables = {**gs, "output_path": gs.get("output_path", "."), "environment": safe_env}
            resolved = VariableInterpolator.interpolate(template, variables)
        if not has_env_placeholder:
            resolved = str(Path(resolved) / safe_env)
        return resolved

    @staticmethod
    def _resolve_env(context: Any, gs: Mapping[str, Any]) -> Optional[str]:
        """Resolve the active environment name, once, for the whole core."""
        return (
            _optional_str(_get(context, "env"))
            or _optional_str(gs.get("env"))
            or _optional_str(gs.get("environment"))
            or _optional_str(_get(context, "environment"))
        )

    @staticmethod
    def _resolve_mlflow_enabled(mlflow_section: Mapping[str, Any]) -> bool:
        """Resolve MLflow enablement from the environment, then configuration."""
        import os

        for name in ("DUCTA_MLFLOW_ENABLED", "Ducta_MLFLOW_ENABLED"):
            raw = os.getenv(name)
            if raw is not None and raw.strip():
                return coerce_bool(name, raw, default=False)
        return coerce_bool("mlflow.enabled", mlflow_section.get("enabled"), default=False)

    @staticmethod
    def _resolve_mlops_enabled(gs: Mapping[str, Any], mlops_section: Mapping[str, Any]) -> bool:
        """Resolve MLOps enablement from the flat flag and the nested section."""
        nested = mlops_section.get("enabled")
        if nested is not None:
            return coerce_bool("mlops.enabled", nested, default=True)
        return coerce_bool("mlops_enabled", gs.get("mlops_enabled"), default=True)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-dict view, for logging and for the run certificate."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _optional_str(value: Any) -> Optional[str]:
    """Normalize to a non-empty string, or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(name: str, value: Any) -> Optional[int]:
    """Normalize to an int, or None; warn rather than raise on garbage."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Setting '{}' has non-numeric value {!r}; ignoring it.", name, value)
        return None
