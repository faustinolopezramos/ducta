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

# What a streaming pipeline will do, said without starting Spark: per node, what it
# reads, what it writes, how often it fires and where its checkpoint will live,
# plus the problems that would stop it (or surprise someone) at start.
#
# One description feeds three readers - `ducta stream plan`, the summary the CLI
# prints when a stream starts, and the per-node line the API shows next to a
# running query - so they cannot disagree.
#
# A summary names places (a topic, a path), never connection options: it is
# printed and serialised, and broker credentials live in those options.

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ducta.stream.checkpoints import CheckpointManager
from ducta.stream.constants import DEFAULT_STREAMING_CONFIG
from ducta.stream.context_utils import get_context_value
from ducta.stream.exceptions import StreamingError
from ducta.stream.query_manager import TransformationRegistry, single_spec
from ducta.stream.validators import StreamingValidator

ERROR = "error"
WARNING = "warning"


@dataclass
class Issue:
    level: str  # "error" | "warning"
    text: str


@dataclass
class NodePlan:
    name: str
    source: str
    sink: str
    trigger: str
    output_mode: str
    checkpoint: Optional[str]
    after: List[str] = field(default_factory=list)
    transform: Optional[str] = None
    issues: List[Issue] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        """The part safe to show next to a running query (no issues, no options)."""
        return {
            "source": self.source,
            "sink": self.sink,
            "trigger": self.trigger,
            "output_mode": self.output_mode,
            "checkpoint": self.checkpoint,
        }


@dataclass
class PipelinePlan:
    pipeline: str
    env: Optional[str]
    nodes: List[NodePlan]
    issues: List[Issue] = field(default_factory=list)  # pipeline-level (not tied to a node)

    @property
    def errors(self) -> List[str]:
        return [i.text for i in self._all_issues() if i.level == ERROR]

    @property
    def warnings(self) -> List[str]:
        return [i.text for i in self._all_issues() if i.level == WARNING]

    def _all_issues(self) -> Iterable[Issue]:
        yield from self.issues
        for node in self.nodes:
            for issue in node.issues:
                yield Issue(issue.level, f"{node.name}: {issue.text}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "env": self.env,
            "ok": not self.errors,
            "nodes": [asdict(n) for n in self.nodes],
            "issues": [asdict(i) for i in self.issues],
        }


# ── one-line descriptions ────────────────────────────────────────────────────


def _option(options: Dict[str, Any], *names: str) -> Optional[str]:
    for name in names:
        value = options.get(name)
        if value not in (None, ""):
            return str(value)
    return None


def describe_source(spec: Any) -> str:
    """``kafka topic events``, ``file_stream json data/events`` - never credentials."""
    if not isinstance(spec, dict):
        return "?"
    fmt = str(spec.get("format") or "?").lower()
    options = spec.get("options") or {}
    if fmt == "kafka":
        topic = _option(options, "subscribe", "subscribePattern", "assign")
        return f"kafka topic {topic}" if topic else "kafka"
    if fmt == "kinesis":
        stream = _option(options, "streamName")
        return f"kinesis {stream}" if stream else "kinesis"
    if fmt == "file_stream":
        path = spec.get("path") or _option(options, "path") or "?"
        return f"file_stream {spec.get('file_format') or 'parquet'} {path}"
    if fmt in ("delta_stream", "delta"):
        change_feed = str(options.get("readChangeFeed", "")).lower() == "true"
        suffix = " (change feed)" if change_feed else ""
        return f"delta {spec.get('path') or '?'}{suffix}"
    if fmt == "rate":
        rate = _option(options, "rowsPerSecond") or "1"
        return f"rate {rate} rows/s"
    if fmt == "socket":
        return f"socket {_option(options, 'host') or '?'}:{_option(options, 'port') or '?'}"
    return fmt


def describe_sink(spec: Any) -> str:
    if not isinstance(spec, dict):
        return "?"
    fmt = str(spec.get("format") or "?").lower()
    if fmt == "kafka":
        topic = _option(spec.get("options") or {}, "topic")
        return f"kafka topic {topic}" if topic else "kafka"
    if fmt in ("console", "memory"):
        return fmt
    return f"{fmt} {spec.get('path') or '?'}"


def describe_trigger(streaming: Dict[str, Any]) -> str:
    trigger = streaming.get("trigger") or {}
    kind = str(trigger.get("type") or DEFAULT_STREAMING_CONFIG["trigger"]["type"]).lower()
    interval = trigger.get("interval")
    if kind == "processing_time":
        return f"every {interval or DEFAULT_STREAMING_CONFIG['trigger']['interval']}"
    if kind == "continuous":
        return f"continuous {interval or '1 second'}"
    if kind == "adaptive":
        return "adaptive"
    return kind  # once / available_now


def _checkpoint_for(
    context: Any, node_name: str, pipeline_name: str, streaming: Dict[str, Any]
) -> str:
    """Where the node's checkpoint will be, without creating it."""
    manager = CheckpointManager(context)
    base = manager.determine_checkpoint_base(streaming.get("checkpoint_location"))
    return manager.build_checkpoint_path(base, pipeline_name, node_name)


def _after(node_config: Dict[str, Any]) -> List[str]:
    from ducta.setting.dependency_inference import get_node_dependencies

    try:
        return get_node_dependencies(node_config)
    except Exception:
        return []


def describe_node(node_config: Dict[str, Any], context: Any, pipeline_name: str) -> NodePlan:
    """Plan for one node; configuration problems are issues, never exceptions."""
    name = str(node_config.get("name") or "?")
    streaming = node_config.get("streaming") or {}
    function = node_config.get("function")
    transform = None
    if isinstance(function, dict):
        transform = function.get("key")
    elif isinstance(function, str):
        transform = function

    plan = NodePlan(
        name=name,
        source=describe_source(single_spec(node_config, "input")),
        sink=describe_sink(single_spec(node_config, "output")),
        trigger=describe_trigger(streaming),
        output_mode=str(streaming.get("output_mode") or DEFAULT_STREAMING_CONFIG["output_mode"]),
        checkpoint=None,
        after=_after(node_config),
        transform=str(transform) if transform else None,
    )
    try:
        plan.checkpoint = _checkpoint_for(context, name, pipeline_name, streaming)
    except StreamingError as e:
        plan.issues.append(Issue(ERROR, e.message))
    except Exception as e:  # noqa: BLE001 - a plan reports, it does not raise
        plan.issues.append(Issue(ERROR, f"could not resolve the checkpoint: {e}"))
    return plan


# ── the whole pipeline ───────────────────────────────────────────────────────


def _resolve_nodes(context: Any, pipeline_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes_config = get_context_value(context, "nodes_config", {}) or {}
    resolved: List[Dict[str, Any]] = []
    for idx, node in enumerate(pipeline_config.get("nodes", []) or []):
        if isinstance(node, str):
            body = nodes_config.get(node)
            if not isinstance(body, dict):
                resolved.append({"name": node, "_missing": True})
                continue
            resolved.append({**body, "name": node})
        elif isinstance(node, dict):
            resolved.append(node if "name" in node else {**node, "name": f"node_{idx}"})
    return resolved


def _load_transforms(registry: TransformationRegistry, modules: Iterable[str]) -> Dict[str, str]:
    """Import each module and let it register; returns ``{module: problem}``."""
    problems: Dict[str, str] = {}
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    for module_path in modules:
        try:
            module = importlib.import_module(module_path)
        except Exception as e:  # noqa: BLE001
            problems[module_path] = f"could not be imported: {e}"
            continue
        register = getattr(module, "register_transforms", None)
        if callable(register):
            try:
                register(registry)
            except Exception as e:  # noqa: BLE001
                problems[module_path] = f"register_transforms() raised: {e}"
    return problems


def plan_pipeline(
    context: Any,
    pipeline_name: str,
    pipeline_config: Optional[Dict[str, Any]] = None,
    extra_transform_modules: Iterable[str] = (),
) -> PipelinePlan:
    """What ``pipeline_name`` would do, and what would stop it. Starts no Spark.

    Importing the transform modules runs their top-level code, exactly as starting
    the stream would.
    """
    if pipeline_config is None:
        pipeline_config = (get_context_value(context, "pipelines_config", {}) or {}).get(
            pipeline_name
        ) or {}
    env = get_context_value(context, "env", None)
    plan = PipelinePlan(pipeline=pipeline_name, env=env, nodes=[])

    node_configs = _resolve_nodes(context, pipeline_config)
    if not node_configs:
        plan.issues.append(Issue(ERROR, "the pipeline has no nodes"))
        return plan

    validator = StreamingValidator(get_context_value(context, "format_policy", None))

    # Transforms: global modules, then each node's own, into one scratch registry.
    registry = TransformationRegistry()
    global_config = get_context_value(context, "global_config", {}) or {}
    modules = list(extra_transform_modules)
    configured = global_config.get("streaming_transform_modules") or []
    modules += [configured] if isinstance(configured, str) else list(configured)
    for cfg in node_configs:
        function = cfg.get("function")
        if isinstance(function, dict) and function.get("module"):
            modules.append(str(function["module"]))
    module_problems = _load_transforms(registry, dict.fromkeys(modules))
    registered = set(registry.list_transformations()) | set(
        TransformationRegistry.class_list_transformations()
    )

    produced = {
        str((single_spec(cfg, "output") or {}).get("path"))
        for cfg in node_configs
        if isinstance(single_spec(cfg, "output"), dict)
    }
    seen_checkpoints: Dict[str, str] = {}

    for cfg in node_configs:
        if cfg.get("_missing"):
            plan.nodes.append(
                NodePlan(
                    cfg["name"], "?", "?", "?", "?", None, issues=[Issue(ERROR, "node not defined")]
                )
            )
            continue
        node = describe_node(cfg, context, pipeline_name)
        try:
            validator.validate_streaming_node_config(cfg)
        except StreamingError as e:
            node.issues.append(Issue(ERROR, e.message))

        if node.transform and node.transform not in registered:
            module = (
                (cfg.get("function") or {}).get("module")
                if isinstance(cfg.get("function"), dict)
                else None
            )
            why = f" ({module} {module_problems[module]})" if module in module_problems else ""
            node.issues.append(Issue(ERROR, f"transform '{node.transform}' is not registered{why}"))

        source = single_spec(cfg, "input")
        if isinstance(source, dict) and str(source.get("format")).lower() in (
            "file_stream",
            "delta_stream",
            "delta",
        ):
            path = source.get("path") or (source.get("options") or {}).get("path")
            if (
                isinstance(path, str)
                and "://" not in path
                and path not in produced
                and not Path(path).exists()
            ):
                node.issues.append(Issue(WARNING, f"source path '{path}' does not exist yet"))

        if node.checkpoint:
            if node.checkpoint in seen_checkpoints:
                node.issues.append(
                    Issue(
                        ERROR,
                        f"shares its checkpoint with '{seen_checkpoints[node.checkpoint]}'",
                    )
                )
            seen_checkpoints[node.checkpoint] = node.name
        plan.nodes.append(node)

    try:
        order = validator.topological_sort({c["name"]: c for c in node_configs})
        plan.nodes.sort(key=lambda n: order.index(n.name) if n.name in order else len(order))
    except StreamingError as e:
        plan.issues.append(Issue(ERROR, e.message))
    return plan
