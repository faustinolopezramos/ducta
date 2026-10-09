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

Why a run failed, in the terms someone fixing it needs:

* **what kind** of failure — the code, the data, a quality gate, the
  configuration, or the infrastructure;
* **where** — the first frame of the project's own code in the traceback,
  not the twenty frames of Spark and Ducta around it;
* **what changed** since the last successful run of the same pipeline in the
  same environment — its code, the data it read, its configuration — read
  from the two runs' certificates.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

#: (kind, patterns) — the first kind with a matching pattern wins. Data before
#: infra: a Spark data error's trace is full of py4j and java.lang frames.
_KINDS = (
    (
        "quality_gate",
        (r"quality gate", r"QualityGateBlocked", r"quality checks failed", r"QualityChecksFailed"),
    ),
    (
        "config",
        (
            r"configuration is invalid",
            r"Invalid project configuration",
            r"ConfigurationError",
            r"not in the catalog",
            r"preflight",
        ),
    ),
    (
        "data",
        (
            r"missing input",
            r"MissingDependency",
            r"Path does not exist",
            r"AnalysisException",
            r"cannot resolve",
            r"UNRESOLVED_COLUMN",
            r"schema",
            r"empty dataset",
            r"is empty",
        ),
    ),
    (
        "infra",
        (
            r"credentials",
            r"connection (refused|reset|timed out)",
            r"OutOfMemory",
            r"java\.lang\.",
            r"Py4J",
            r"timed out",
            r"TimeoutError",
            r"No space left",
            r"Permission denied",
            r"JDBC",
        ),
    ),
    ("code", (r"Traceback", r"Error\b", r"Exception\b")),
)

_TITLES = {
    "quality_gate": "A quality gate stopped the run",
    "config": "The configuration is wrong",
    "infra": "The infrastructure failed (connection, memory, credentials)",
    "data": "The data was not what the node expected",
    "code": "The node's code raised an error",
    "unknown": "The run failed",
}

_FRAME = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<fn>[^\s]+)')
_NOT_USER = ("site-packages", "/ducta/", "\\ducta\\", "<frozen", "py4j", "pyspark", "/lib/python")


_NODE_IN = re.compile(r"node '(?P<n>[^']+)'")


def _node_in(text: str) -> Optional[str]:
    m = _NODE_IN.search(text or "")
    return m["n"] if m else None


def classify(text: str) -> str:
    for kind, patterns in _KINDS:
        if any(re.search(p, text or "", re.IGNORECASE) for p in patterns):
            return kind
    return "unknown"


def first_user_frame(traceback: str, project_root: Path) -> Optional[Dict[str, Any]]:
    """The innermost frame in the project's own code (the one to open)."""
    root = str(Path(project_root).resolve())
    found: Optional[Dict[str, Any]] = None
    for m in _FRAME.finditer(traceback or ""):
        path = m["file"]
        if any(marker in path for marker in _NOT_USER):
            continue
        try:
            rel = str(Path(path).resolve().relative_to(root).as_posix())
        except ValueError:
            continue
        found = {"file": rel, "line": int(m["line"]), "function": m["fn"]}
    return found


def _fingerprint(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("fingerprint") or value.get("hash") or value.get("sha256") or value
    return value


def what_changed(failed: Dict[str, Any], last_ok: Dict[str, Any]) -> Dict[str, Any]:
    """Code, data and configuration differences between a failed run and the last good one."""
    code_now = (failed.get("code") or {}).get("nodes") or {}
    code_then = (last_ok.get("code") or {}).get("nodes") or {}
    # Only what the failed run ran: a partial run (one node, a scope) did not
    # "change" the nodes and inputs it never touched.
    code = sorted(
        key
        for key in code_now
        if (code_now.get(key) or {}).get("source_hash")
        != (code_then.get(key) or {}).get("source_hash")
    )
    inputs_now = failed.get("inputs") or {}
    inputs_then = last_ok.get("inputs") or {}
    data = sorted(
        key
        for key in inputs_now
        if _fingerprint(inputs_now.get(key)) != _fingerprint(inputs_then.get(key))
    )
    return {
        "since_run_id": last_ok.get("run_id"),
        "since": last_ok.get("started_at"),
        "since_commit": (last_ok.get("environment") or {}).get("git_commit"),
        "code": code,
        "data": data,
        "config": failed.get("config_fingerprint") != last_ok.get("config_fingerprint"),
    }


def suggestions(
    kind: str, frame: Optional[Dict[str, Any]], changed: Optional[Dict[str, Any]]
) -> List[str]:
    out: List[str] = []
    if changed:
        if changed["code"]:
            out.append(
                "The code changed since the last good run — compare it with that version first."
            )
        if changed["data"]:
            out.append("The input data changed — preview it and check the rows the node failed on.")
        if changed["config"]:
            out.append("The configuration changed — compare the environments in Settings.")
    if kind == "quality_gate":
        out.append("Open the quality report to see which checks failed and on which rows.")
    elif kind == "config":
        out.append("Run Validate (⌘⇧V): it lists every configuration problem with its line.")
    elif kind == "infra":
        out.append(
            "Retry once the connection, credentials or resources are back — nothing in the project needs to change."
        )
    elif kind == "data":
        out.append("Check that the upstream datasets exist and have the columns the node reads.")
    if frame:
        out.append(f"The error is raised in {frame['file']}:{frame['line']} ({frame['function']}).")
    return out


def diagnose(
    execution: Dict[str, Any],
    errors: List[Dict[str, Any]],
    project_root: Optional[Path],
    certificate: Optional[Dict[str, Any]],
    last_ok: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    first = errors[0] if errors else {}
    text = " ".join(
        str(x)
        for x in (
            execution.get("error_message"),
            first.get("error_type"),
            first.get("message"),
            first.get("traceback"),
        )
        if x
    )
    kind = classify(text)
    frame = first_user_frame(first.get("traceback") or "", project_root) if project_root else None
    changed = what_changed(certificate, last_ok) if certificate and last_ok else None
    return {
        "execution_id": execution.get("id"),
        "status": execution.get("status"),
        "kind": kind,
        "title": _TITLES.get(kind, _TITLES["unknown"]),
        "message": first.get("message") or execution.get("error_message"),
        "node": first.get("node_id") or _node_in(text),
        "frame": frame,
        "what_changed": changed,
        "suggestions": suggestions(kind, frame, changed),
        "hint": first.get("hint"),
    }
