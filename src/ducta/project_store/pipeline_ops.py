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

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

_ALIAS = re.compile(r"[^A-Za-z0-9_]")
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
    """Where a new key disturbs nothing: after the last key holding a plain value."""
    position = 0
    for index, value in enumerate(mapping.values()):
        if not isinstance(value, (dict, list)):
            position = index + 1
    return position


def _end_slot(doc: Any) -> Optional[List[Any]]:
    """Where ruamel keeps the comments written after the last node: the document's
    end, or what comes before the next top-level key (``None`` when there are none)."""
    keys = list(doc.keys())
    if "nodes" not in keys:
        return None
    index = keys.index("nodes")
    if index == len(keys) - 1:
        return doc.ca.end  # type: ignore[no-any-return]
    item = doc.ca.items.get(keys[index + 1])
    return item[1] if item and len(item) > 1 else None


def _take_node_tail(doc: Any) -> List[Any]:
    """The indented comments after the last node, removed from where ruamel keeps
    them. A key added after that node would otherwise carry them off — they read as
    the new node's, and leave with it when it is removed (an undo dropped them)."""
    slot = _end_slot(doc)
    if not slot:
        return []
    n = 0
    while n < len(slot) and (slot[n].column > 0 or not str(slot[n].value).strip()):
        n += 1
    taken = list(slot[:n])
    del slot[:n]
    return taken


def _give_node_tail(doc: Any, tokens: List[Any]) -> None:
    """Put *tokens* back after the last node (see :func:`_take_node_tail`)."""
    keys = list(doc.keys())
    index = keys.index("nodes")
    if index == len(keys) - 1:
        doc.ca.end = tokens + list(doc.ca.end or [])
        if doc.ca.comment is None:  # ruamel writes the end comments only with this slot
            doc.ca.comment = [None, None]
        return
    item = doc.ca.items.setdefault(keys[index + 1], [None, None, None, None])
    item[1] = tokens + list(item[1] or [])


def _last_comment(value: Any) -> Optional[Tuple[List[Any], int]]:
    """Where ruamel keeps what is written after *value*'s last line: the comment slot
    of its deepest last scalar (``None`` when it has none)."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if isinstance(value, CommentedMap) and len(value):
        key = list(value.keys())[-1]
        deeper = _last_comment(value[key])
        if deeper:
            return deeper
        item = value.ca.items.get(key)
        return (item, 2) if item and len(item) > 2 and item[2] is not None else None
    if isinstance(value, CommentedSeq) and len(value):
        deeper = _last_comment(value[-1])
        if deeper:
            return deeper
        item = value.ca.items.get(len(value) - 1)
        return (item, 0) if item and item[0] is not None else None
    return None


#: One line of a comment block: its indentation and text ("" for a blank line).
_Line = Tuple[int, str]


def _line(raw: str, column: int) -> _Line:
    if not raw.strip():
        return (0, "")
    indent = len(raw) - len(raw.lstrip())
    return (indent if indent else column, raw.strip())


def _cut_tail(body: Any, column: int) -> List[_Line]:
    """Cut from *body*'s tail the comments written at *column* or left of it — above
    the next node, not in this one — with the blank lines before them."""
    slot = _last_comment(body)
    if slot is None:
        return []
    holder, index = slot
    lines = str(holder[index].value).split("\n")  # lines[0] ends the value's own line
    first = next(
        (
            i
            for i, raw in enumerate(lines)
            if i and raw.strip().startswith("#") and len(raw) - len(raw.lstrip()) <= column
        ),
        None,
    )
    if first is None:
        return []
    while first > 1 and not lines[first - 1].strip():
        first -= 1
    rest = "\n".join(lines[:first]) + "\n"
    if rest.strip():
        holder[index].value = rest
    else:
        holder[index] = None
    cut = lines[first:]
    if cut and cut[-1] == "":
        cut.pop()
    return [_line(raw, column) for raw in cut]


def _take_above(doc: Any, name: str, column: int) -> List[_Line]:
    """Take every comment line written above node *name* at the nodes' indentation,
    wherever ruamel keeps it: the previous node's tail, the top of ``nodes:``, or
    the slot before the key."""
    nodes = doc["nodes"]
    names = list(nodes.keys())
    index = names.index(name)
    lines: List[_Line] = []
    if index:
        lines += _cut_tail(nodes[names[index - 1]], column)
    else:
        top = nodes.ca.comment[1] if nodes.ca.comment and len(nodes.ca.comment) > 1 else None
        slot = doc.ca.items.get("nodes")
        if not top and slot and len(slot) > 3:
            top = slot[3]
        for token in top or []:
            lines += _token_lines(token)
        if nodes.ca.comment and len(nodes.ca.comment) > 1:
            nodes.ca.comment[1] = None
        if slot and len(slot) > 3:
            slot[3] = None
    item = nodes.ca.items.get(name)
    if item and len(item) > 1 and item[1]:
        for token in item[1]:
            lines += _token_lines(token)
        item[1] = None
    return lines


def _token_lines(token: Any) -> List[_Line]:
    raws = str(token.value).split("\n")
    if raws and raws[-1] == "":
        raws.pop()
    return [_line(raw, token.column) for raw in raws]


def _put_above(nodes: Any, name: str, lines: List[_Line]) -> None:
    """Write *lines* above node *name* (the slot ruamel writes before its key)."""
    if not lines:
        return
    from ruamel.yaml.error import CommentMark
    from ruamel.yaml.tokens import CommentToken

    tokens = [
        CommentToken(f"{text}\n" if text else "\n", CommentMark(indent if text else 0), None)
        for indent, text in lines
    ]
    item = nodes.ca.items.setdefault(name, [None, None, None, None])
    item[1] = tokens + list(item[1] or [])


def _node_column(nodes: Any) -> int:
    """The column the node names are written at (2 for a new file)."""
    for key in nodes:
        if key in nodes.lc.data:
            return int(nodes.lc.data[key][1])
    return 2


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
        before = op.get("before")
        if isinstance(before, str) and before in nodes:
            # Back where it was (an undo of remove_node): of the comments above
            # `before`, its own last `before_comments` lines stay with it; the rest
            # were written above this node.
            lines = _take_above(doc, before, _node_column(nodes))
            own = op.get("before_comments")
            own = min(own, len(lines)) if isinstance(own, int) and own > 0 else 0
            nodes.insert(list(nodes.keys()).index(before), name, body)
            _put_above(nodes, name, lines[: len(lines) - own])
            _put_above(nodes, before, lines[len(lines) - own :])
            return {"op": "remove_node", "node": name}
        # The last node's trailing comments stay above the new one, still the last node's.
        tail = _take_node_tail(doc) if len(nodes) else []
        nodes[name] = body
        if tail:
            nodes.ca.items[name] = [None, tail, None, None]
        return {"op": "remove_node", "node": name}

    node = _node(doc, name)

    if kind == "remove_node":
        body = _plain(node)
        nodes = doc["nodes"]
        names = list(nodes.keys())
        following = names[names.index(name) + 1] if names.index(name) + 1 < len(names) else None
        if following is not None:
            # No comment leaves with the node: the ones above it and the ones above
            # the next node (ruamel keeps those in this node's tail) stay, above the
            # next node. The undo puts the node back between them.
            column = _node_column(nodes)
            above_this = _take_above(doc, name, column)
            above_next = _take_above(doc, following, column)
            del nodes[name]
            nodes.ca.items.pop(name, None)
            _put_above(nodes, following, above_this + above_next)
            return {
                "op": "add_node",
                "node": name,
                "body": body,
                "before": following,
                "before_comments": len(above_next),
            }
        # The comments written above the last node belong to the one before it: they
        # stay after the last one.
        before = nodes.ca.items.get(name)
        kept = [t for t in (before[1] or [])] if before and len(before) > 1 else []
        del nodes[name]
        nodes.ca.items.pop(name, None)
        if kept:
            _give_node_tail(doc, kept)
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
        alias = None
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
        field = op.get("key")
        if field not in SETTABLE:
            raise OpError(
                f"'{field}' cannot be set this way (one of: {', '.join(sorted(SETTABLE))})"
            )
        old = _plain(node.get(field)) if field in node else None
        value = op.get("value")
        if value is None:
            node.pop(field, None)
        elif field in node:
            node[field] = copy.deepcopy(value)
        else:
            node.insert(_quiet_position(node), field, copy.deepcopy(value))
        return {"op": "set", "node": name, "key": field, "value": old}

    raise OpError(f"unknown operation '{kind}'")


def apply_ops(doc: Any, ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply in order; the inverses come back in undo order (last first)."""
    return [apply_op(doc, op) for op in ops][::-1]
