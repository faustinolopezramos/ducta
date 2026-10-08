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

The ML contract between a pipeline file and a node: what split a node receives,
where it came from, and which nodes are bound to apply it.

A train/test split written in YAML is a promise about the data a model was fitted
and scored on. Ducta delivers it to the node as ``ml_context.split``, but only the
node's own code can apply it (``ducta.mlrun.split_dataframe``). These rules decide
who must keep the promise, so that one who does not is an error instead of a model
trained on a partition nobody declared:

* A ``split:`` on a node is that node's; it overrides the pipeline's.
* A ``split:`` on the pipeline is for the nodes that fit or score a model — those
  with ``ml_stage: training`` or ``evaluation``. A feature-engineering node receives
  it too (it may want to know), but is not bound to apply it.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from ducta.core.errors import ExecutionError

#: Stages whose nodes fit or score a model, and so must apply the pipeline's split.
SPLIT_STAGES = frozenset({"training", "evaluation"})

#: ``settings.split_enforcement`` values.
SPLIT_ENFORCEMENT = ("error", "warn")


class SplitNotAppliedError(ExecutionError):
    """A node bound to a declared split finished without applying it."""


def _plain(value: Any) -> Any:
    if value is not None and hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    return value


def node_stage(node_config: Mapping[str, Any]) -> str:
    """The node's ML stage as plain text (``""`` when it has none)."""
    from ducta.core.mlops_auto_config import MLOpsAutoConfigurator

    return MLOpsAutoConfigurator.resolve_ml_stage(dict(node_config or {})).lower()


def node_split(node_config: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The split the node declares itself, if any."""
    split = _plain((node_config or {}).get("split"))
    return dict(split) if split else None


def effective_split(
    node_config: Mapping[str, Any], pipeline_split: Any
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """``(split, source)``: the node's own split, else the pipeline's; source is
    ``"node"``, ``"pipeline"`` or ``None``."""
    own = node_split(node_config)
    if own:
        return own, "node"
    inherited = _plain(pipeline_split)
    if inherited:
        return dict(inherited), "pipeline"
    return None, None


def must_apply_split(node_config: Mapping[str, Any], pipeline_split: Any) -> bool:
    """Whether this node is bound to apply a split (see the module docstring)."""
    if node_split(node_config):
        return True
    return bool(_plain(pipeline_split)) and node_stage(node_config) in SPLIT_STAGES


def describe_split(split: Optional[Mapping[str, Any]]) -> str:
    """``method=stratified, test_size=0.2, stratify_col=y, seed=42`` — for messages."""
    if not split:
        return "none"
    order = ("method", "test_size", "val_size", "stratify_col", "time_col", "group_col", "seed")
    parts = [f"{k}={split[k]}" for k in order if split.get(k) is not None]
    parts += [f"{k}={v}" for k, v in split.items() if k not in order and v is not None]
    return ", ".join(parts)


def not_applied_message(node_name: str, split: Mapping[str, Any], source: Optional[str]) -> str:
    where = "on the node" if source == "node" else "on the pipeline"
    return (
        f"Node '{node_name}' was given a train/test split ({describe_split(split)}, declared "
        f"{where}) but never applied it, so its model was fitted and scored on a partition "
        "nobody declared. Apply it in the node: "
        "`train, test = split_dataframe(df, ml_context.split, ml_context=ml_context)` "
        "(from ducta.mlrun). To let the run continue anyway, set "
        "`settings.split_enforcement: warn`."
    )
