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

Small, invertible edits to a format-2 pipeline file — what the canvas does.

Each operation changes one thing in the round-trip YAML document, so the rest
of the file (comments, key order, everything not named) is untouched, and
each has an inverse the client can send to undo it:

=================  ==========================================  =================
op                 does                                        inverse
=================  ==========================================  =================
connect            node reads dataset (as ``alias``)           disconnect
disconnect         node no longer reads dataset                connect (alias)
add_output         node writes dataset                         remove_output
remove_output      node no longer writes dataset               add_output
add_node           a new node                                  remove_node
remove_node        a node is gone                              add_node (body)
set                one key of a node (``value: null`` drops)   set (old value)
=================  ==========================================  =================

Every result says what the inverse is, so undo does not have to guess.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

_ALIAS = re.compile(r"[^A-Za-z0-9_]")
#: Keys `set` may change. Structure (inputs/outputs/kind/run) has its own ops.
SETTABLE = {
    "description",
    "retry",
    "timeout_seconds",
    "on_missing_input",
    "fail_fast",
    "metadata",
    "quality",
    "ingest",
    "after",
    "run",
}


class OpError(ValueError):
    """An operation that does not apply to the document as it is."""


def default_alias(dataset: str, taken: List[str]) -> str:
    """The parameter name a dataset gets: its last segment, made an identifier, unique."""
    base = _ALIAS.sub("_", dataset.rsplit(".", 1)[-1]) or "data"
    if base[0].isdigit():
        base = f"_{base}"
    alias, n = base, 2
    while alias in taken:
        alias, n = f"{base}_{n}", n + 1
    return alias


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _quiet_position(mapping: Any) -> int:
    """Where a new key disturbs nothing: after the last key holding a plain value.

    Not at the end — the comments and blank lines that follow a nested block
    (``quality: …`` and whatever is written after it) belong to the block's
    last line, and a key appended after it would carry them off.
    """
    position = 0
    for index, value in enumerate(mapping.values()):
        if not isinstance(value, (dict, list)):
            position = index + 1
    return position


def _node(doc: Any, name: str) -> Any:
    nodes = doc.get("nodes") if isinstance(doc, dict) else None
    if not isinstance(nodes, dict) or name not in nodes:
        raise OpError(f"node '{name}' is not in this pipeline")
    return nodes[name]


def apply_op(doc: Any, op: Dict[str, Any]) -> Dict[str, Any]:
    """Apply one operation to a pipeline document in place; returns its inverse."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    kind = op.get("op")
    name = op.get("node")
    if not isinstance(name, str) or not name:
        raise OpError("every operation names a 'node'")

    if kind == "add_node":
        nodes = doc.setdefault("nodes", CommentedMap())
        if name in nodes:
            raise OpError(f"node '{name}' already exists")
        body = CommentedMap()
        if op.get("use"):  # an instance of a node template (ADR 0001 §3)
            body["use"] = op["use"]
            if op.get("with"):
                body["with"] = CommentedMap(op["with"])
        for key in ("description", "run", "kind"):
            if op.get(key):
                body[key] = op[key]
        inputs = op.get("inputs")
        if isinstance(inputs, dict) and inputs:
            body["inputs"] = CommentedMap(inputs)
        elif isinstance(inputs, list) and inputs:
            body["inputs"] = CommentedSeq(inputs)
        outputs = op.get("outputs")
        if outputs:
            body["outputs"] = CommentedSeq(outputs)
        for key, value in (op.get("body") or {}).items():
            body[key] = copy.deepcopy(value)
        nodes[name] = body
        return {"op": "remove_node", "node": name}

    node = _node(doc, name)

    if kind == "remove_node":
        body = _plain(node)
        del doc["nodes"][name]
        return {"op": "add_node", "node": name, "body": body}

    if kind == "connect":
        dataset = op.get("dataset")
        if not isinstance(dataset, str) or not dataset:
            raise OpError("connect needs a 'dataset'")
        inputs = node.get("inputs")
        if inputs is None:
            alias = op.get("alias") or default_alias(dataset, [])
            node["inputs"] = CommentedMap({alias: dataset})
        elif isinstance(inputs, dict):
            if dataset in inputs.values():
                raise OpError(f"node '{name}' already reads '{dataset}'")
            alias = op.get("alias") or default_alias(dataset, list(inputs.keys()))
            if alias in inputs:
                raise OpError(f"node '{name}' already has an input named '{alias}'")
            inputs[alias] = dataset
        elif isinstance(inputs, list):
            if dataset in inputs:
                raise OpError(f"node '{name}' already reads '{dataset}'")
            alias = None
            inputs.append(dataset)
        else:
            raise OpError(f"node '{name}' has inputs this cannot edit")
        return {"op": "disconnect", "node": name, "dataset": dataset, "alias": alias}

    if kind == "disconnect":
        dataset = op.get("dataset")
        inputs = node.get("inputs")
        alias: Optional[str] = None
        if isinstance(inputs, dict):
            keys = [k for k, v in inputs.items() if v == dataset]
            if not keys:
                raise OpError(f"node '{name}' does not read '{dataset}'")
            alias = str(keys[0])
            del inputs[keys[0]]
        elif isinstance(inputs, list) and dataset in inputs:
            inputs.remove(dataset)
        else:
            raise OpError(f"node '{name}' does not read '{dataset}'")
        if not inputs:
            del node["inputs"]
        return {"op": "connect", "node": name, "dataset": dataset, "alias": alias}

    if kind in ("add_output", "remove_output"):
        dataset = op.get("dataset")
        if not isinstance(dataset, str) or not dataset:
            raise OpError(f"{kind} needs a 'dataset'")
        outputs = node.get("outputs")
        if kind == "add_output":
            if outputs is None:
                node["outputs"] = CommentedSeq([dataset])
            elif dataset in outputs:
                raise OpError(f"node '{name}' already writes '{dataset}'")
            else:
                outputs.append(dataset)
            return {"op": "remove_output", "node": name, "dataset": dataset}
        if not outputs or dataset not in outputs:
            raise OpError(f"node '{name}' does not write '{dataset}'")
        outputs.remove(dataset)
        if not outputs:
            del node["outputs"]
        return {"op": "add_output", "node": name, "dataset": dataset}

    if kind == "set":
        key = op.get("key")
        if key not in SETTABLE:
            raise OpError(f"'{key}' cannot be set this way (one of: {', '.join(sorted(SETTABLE))})")
        old = _plain(node.get(key)) if key in node else None
        value = op.get("value")
        if value is None:
            node.pop(key, None)
        elif key in node:
            node[key] = copy.deepcopy(value)
        else:
            node.insert(_quiet_position(node), key, copy.deepcopy(value))
        return {"op": "set", "node": name, "key": key, "value": old}

    raise OpError(f"unknown operation '{kind}'")


def apply_ops(doc: Any, ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply in order; the inverses come back in undo order (last first)."""
    return [apply_op(doc, op) for op in ops][::-1]
