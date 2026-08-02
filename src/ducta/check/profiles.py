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

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.check.core import QualityConfigError
from ducta.check.storage import DEFAULT_PIPELINE_NAME


@dataclass
class QualityProfile:
    name: str
    checks: Dict[str, Any] = field(default_factory=dict)
    auto_tune: bool = False


def load_profiles(global_settings: Dict[str, Any]) -> Dict[str, QualityProfile]:
    quality_cfg = (global_settings or {}).get("quality") or {}
    raw_profiles = quality_cfg.get("profiles") or {}
    profiles = {}
    for name, data in raw_profiles.items():
        if not isinstance(data, dict):
            logger.warning("Quality profile '{}' is not a dict, skipping", name)
            continue
        profiles[name] = QualityProfile(
            name=name,
            checks=deepcopy(data.get("checks") or {}),
            auto_tune=bool(data.get("auto_tune", False)),
        )
    return profiles


def resolve_checks_config(
    node_checks: Dict[str, Any],
    profile_name: Optional[str],
    profiles: Dict[str, QualityProfile],
) -> Dict[str, Any]:
    """Merge a profile's default checks with node-level check overrides."""
    if not profile_name:
        return node_checks

    profile = profiles.get(profile_name)
    if profile is None:
        # A typo'd profile name used to just fall back to the node's own
        # checks with a warning — silently dropping every check the profile
        # was meant to add, with no visible failure anywhere.
        raise QualityConfigError(
            f"Quality profile '{profile_name}' not found. "
            f"Available profiles: {sorted(profiles.keys()) or 'none configured'}"
        )

    merged = {k: deepcopy(v) if isinstance(v, dict) else {} for k, v in profile.checks.items()}
    for key, cfg in node_checks.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(cfg, dict):
            merged[key] = {**merged[key], **cfg}
        else:
            merged[key] = deepcopy(cfg) if isinstance(cfg, dict) else cfg

    return merged


def apply_auto_tune(
    profile: Optional[QualityProfile],
    gate_cfg: Optional[Dict[str, Any]],
    dataset_name: Optional[str],
    storage: Optional[Any],
    pipeline_name: str = DEFAULT_PIPELINE_NAME,
) -> Optional[Dict[str, Any]]:
    """Apply a profile's ``auto_tune`` proposed score_threshold to a gate config.

    Returns *gate_cfg* unchanged (same object) unless the profile has
    ``auto_tune: true``, a *dataset_name*/*storage* are available to look up
    run history, and :class:`~ducta.check.advisor.ThresholdAdvisor` has
    enough history to propose a threshold — in which case a **new** dict with
    ``score_threshold`` overridden is returned (the input is never mutated).
    A ``None`` *gate_cfg* (no per-node ``quality_gate`` block) is treated as an
    empty dict for this purpose, so auto_tune still works when gating relies
    solely on ``global_settings.quality.gate``.
    """
    if not profile or not profile.auto_tune or not dataset_name or storage is None:
        return gate_cfg
    if gate_cfg is not None and not isinstance(gate_cfg, dict):
        return gate_cfg
    # A node without its own quality_gate block (gate_cfg=None) is the common case
    # when gating relies solely on global_settings.quality.gate — auto_tune must
    # still be able to propose a score_threshold in that case, not silently no-op.
    gate_cfg = gate_cfg or {}

    try:
        from ducta.check.advisor import ThresholdAdvisor

        analysis = ThresholdAdvisor(storage).analyze_history(dataset_name, pipeline_name)
        proposed = analysis.get("proposed_thresholds") or {}
        if analysis.get("ready") and "score_threshold" in proposed:
            tuned = {**gate_cfg, "score_threshold": proposed["score_threshold"]}
            logger.info(
                "auto_tune: set score_threshold={} for '{}'",
                proposed["score_threshold"],
                dataset_name,
            )
            return tuned
    except Exception as e:
        logger.warning("auto_tune failed for '{}': {}", dataset_name, e)

    return gate_cfg
