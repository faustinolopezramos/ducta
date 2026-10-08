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
from typing import Any, Dict, List, Mapping, Optional, Tuple

from loguru import logger  # type: ignore

from ducta.core.context_utils import get_context_value as _get
from ducta.setting.environments import sanitize_env_for_path
from ducta.setting.interpolator import VariableInterpolator

_TRUE_VALUES = frozenset({"true", "yes", "on", "1"})
_FALSE_VALUES = frozenset({"false", "no", "off", "0", ""})
MAX_TIMEOUT_SECONDS = 86_400

DEFAULT_EXECUTION_TIMEOUT_SECONDS = 3_600
DEFAULT_NODE_TIMEOUT_SECONDS = 1_800
DEFAULT_MAX_PARALLEL_NODES = 4
DEFAULT_MAX_STREAMING_PIPELINES = 5
DEFAULT_CERTIFICATE_DIR = "${output_path}/${environment}/.ducta/runs"
DEFAULT_CHAIN_STATE_DIR = "${output_path}/${environment}/.ducta/chain_state"
DEFAULT_RUN_LOCK_DIR = "${output_path}/${environment}/.ducta/locks"

CHAIN_ON_GATE_BLOCKED_STOP = "stop"
CHAIN_ON_GATE_BLOCKED_CONTINUE = "continue"
CHAIN_ON_GATE_BLOCKED_CHOICES = (CHAIN_ON_GATE_BLOCKED_STOP, CHAIN_ON_GATE_BLOCKED_CONTINUE)
EVIDENCE_OFF = "off"  # no certificate
EVIDENCE_RECORD = "record"  # certificate written; failing to write it only warns
EVIDENCE_REQUIRED = "required"  # a run that cannot write its certificate fails
EVIDENCE_SIGNED = "signed"  # required + HMAC-signed; preflight fails without a key
EVIDENCE_LEVELS = (EVIDENCE_OFF, EVIDENCE_RECORD, EVIDENCE_REQUIRED, EVIDENCE_SIGNED)


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
    split_enforcement: str = "error"
    mlflow_enabled: bool = False
    fingerprint_policy: str = "record"

    # ── Run certificates ─────────────────────────────────────────────────────
    evidence_level: str = EVIDENCE_RECORD
    evidence_problems: Tuple[str, ...] = ()
    enable_run_certificate: bool = True
    require_run_certificate: bool = False
    run_certificate_dir: str = DEFAULT_CERTIFICATE_DIR
    certificate_signing_key: Optional[str] = None

    # ── Chain reuse ──────────────────────────────────────────────────────────
    chain_reuse_materialized: bool = False
    chain_staleness_check: bool = True
    chain_on_gate_blocked: str = CHAIN_ON_GATE_BLOCKED_STOP
    chain_state_dir: str = DEFAULT_CHAIN_STATE_DIR

    # ── Run lock (see ducta.core.run_lock) ───────────────────────────────────
    run_lock_enabled: bool = True
    run_lock_backend: str = "local"
    run_lock_ttl_seconds: int = 300
    run_lock_on_conflict: str = "fail"
    run_lock_wait_timeout_seconds: int = 600
    run_lock_dir: str = DEFAULT_RUN_LOCK_DIR

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
        run_lock_section = _as_mapping(gs.get("run_lock"))
        resolved_env = cls._resolve_env(context, gs)
        evidence_level, enable_certificate, require_certificate, evidence_problems = (
            cls._resolve_evidence(gs)
        )

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
            split_enforcement=(
                "warn"
                if str(gs.get("split_enforcement") or "").strip().lower() == "warn"
                else "error"
            ),
            mlflow_enabled=cls._resolve_mlflow_enabled(mlflow_section),
            fingerprint_policy=str(gs.get("fingerprint_policy") or "record"),
            evidence_level=evidence_level,
            evidence_problems=evidence_problems,
            enable_run_certificate=enable_certificate,
            require_run_certificate=require_certificate,
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
            run_lock_enabled=coerce_bool(
                "run_lock.enabled", run_lock_section.get("enabled"), default=True
            ),
            run_lock_backend=coerce_choice(
                "run_lock.backend",
                run_lock_section.get("backend"),
                choices=("local", "storage"),
                default="local",
            ),
            run_lock_ttl_seconds=coerce_int(
                "run_lock.ttl_seconds", run_lock_section.get("ttl_seconds"), default=300, minimum=10
            ),
            run_lock_on_conflict=coerce_choice(
                "run_lock.on_conflict",
                run_lock_section.get("on_conflict"),
                choices=("fail", "wait"),
                default="fail",
            ),
            run_lock_wait_timeout_seconds=coerce_int(
                "run_lock.wait_timeout_seconds",
                run_lock_section.get("wait_timeout_seconds"),
                default=600,
                minimum=0,
            ),
            run_lock_dir=cls._resolve_scoped_dir(
                str(run_lock_section.get("dir") or DEFAULT_RUN_LOCK_DIR), gs, resolved_env
            ),
            quality=_as_mapping(gs.get("quality")),
            ingestion=_as_mapping(gs.get("ingestion")),
        )

    @staticmethod
    def _resolve_scoped_dir(template: str, gs: Mapping[str, Any], env: Optional[str]) -> str:
        """Resolve a Ducta-managed state-directory template (run certificates,
        chain state) to a concrete, environment-scoped path.
        """
        safe_env = sanitize_env_for_path(env)
        has_env_placeholder = "${environment}" in template
        resolved = template
        if "${" in template:
            variables = {**gs, "output_path": gs.get("output_path", "."), "environment": safe_env}
            resolved = VariableInterpolator.interpolate(template, variables)
        if not has_env_placeholder:
            if "://" in resolved:
                # `Path` would collapse `s3://bucket` to `s3:/bucket`.
                resolved = f"{resolved.rstrip('/')}/{safe_env}"
            else:
                resolved = str(Path(resolved) / safe_env)
        return resolved

    @staticmethod
    def _resolve_evidence(gs: Mapping[str, Any]) -> Tuple[str, bool, bool, Tuple[str, ...]]:
        """Resolve ``evidence_level`` into the policy: (level, enabled, required, problems)."""
        problems: List[str] = []
        raw_level = gs.get("evidence_level")
        if raw_level is None:
            level = EVIDENCE_RECORD
        else:
            level = str(raw_level).strip().lower()
            if level not in EVIDENCE_LEVELS:
                problems.append(
                    f"evidence_level {raw_level!r} is not one of {', '.join(EVIDENCE_LEVELS)}"
                )
                level = EVIDENCE_REQUIRED
        return (
            level,
            level != EVIDENCE_OFF,
            level in (EVIDENCE_REQUIRED, EVIDENCE_SIGNED),
            tuple(problems),
        )

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
