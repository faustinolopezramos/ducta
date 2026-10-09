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

Structured problems.

The project loader and the preflight report problems as one-line strings —
``pipelines/silver.clean.yaml:12 node 'x' reads 'y', which is not in the
catalog (did you mean 'z'?)`` — which is what the CLI prints. A UI needs the
same problem split into parts it can act on: which file and line to open,
which node to select, and, when the message carries a suggestion, a fix to
offer. :func:`parse_problem` does that split without changing the strings, so
the CLI output stays exactly as it is.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Literal, Optional

Severity = Literal["error", "warning", "info"]

_LOCATION = re.compile(
    r"^(?P<file>[^\s:'\"]+\.(?:ya?ml|toml|json|py)):(?P<line>\d+)(?::(?P<col>\d+))?:?\s*(?P<rest>.*)$",
    re.S,
)
_FILE_ONLY = re.compile(r"^(?P<file>[^\s:'\"]+\.(?:ya?ml|toml|json|py)):\s*(?P<rest>.*)$", re.S)
_NODE = re.compile(r"\b[Nn]ode '(?P<v>[^']+)'")
_PIPELINE = re.compile(r"\b[Pp]ipeline '(?P<v>[^']+)'")
_DATASET = re.compile(
    r"(?:reads|writes|output|input|compares with|dataset) '(?P<v>[^']+)'|'(?P<w>[^']+)' is written by both"
)
_SUGGESTION = re.compile(r"\(?did you mean '(?P<v>[^']+)'\?\)?")
#: ``pipelines/<pipeline>.nodes.<node>.<key…>: message`` — a schema error's dotted path.
_KEY_PATH = re.compile(r"^(?P<path>(?:pipelines/|catalog\.)\S+?):\s+(?P<msg>.*)$", re.S)
_UNQUOTED = re.compile(r"'(?P<v>[^']+)'")

#: (code, substring) — the first that matches names the problem.
_CODES = (
    ("unknown_dataset", "which is not in the catalog"),
    ("duplicate_writer", "is written by both"),
    ("cycle", "cycle"),
    ("function_not_found", "cannot load function"),
    ("duplicate_definition", "already defined"),
    ("duplicate_definition", "also defined"),
    ("unknown_key", "extra inputs are not permitted"),
    ("unknown_key", "unknown key"),
    ("missing_field", "field required"),
    ("pipeline_not_found", "not found. available"),
    ("unknown_node", "is not a node of pipeline"),
    ("invalid_split", "invalid split"),
    ("invalid_model", "invalid model"),
)


@dataclass
class Fix:
    """A change that would resolve the problem; ``replace`` is ``[old, new]``."""

    label: str
    replace: List[str]


@dataclass
class Problem:
    severity: Severity
    message: str
    code: str = "config"
    source: str = "config"
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    node: Optional[str] = None
    pipeline: Optional[str] = None
    dataset: Optional[str] = None
    fix: Optional[Fix] = None
    raw: str = field(default="", repr=False)

    def __str__(self) -> str:
        return self.raw or self.message

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        return data


def _code_for(text: str) -> str:
    lowered = text.lower()
    for code, needle in _CODES:
        if needle in lowered:
            return code
    return "config"


def parse_problem(text: str, severity: Severity = "error", source: str = "config") -> Problem:
    """Split one problem string into its parts; unknown shapes keep only the message."""
    raw = str(text).strip()
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    rest = raw

    m = _LOCATION.match(raw)
    if m:
        file, line = m["file"], int(m["line"])
        column = int(m["col"]) if m["col"] else None
        rest = m["rest"].strip()
    else:
        m = _FILE_ONLY.match(raw)
        if m:
            file, rest = m["file"], m["rest"].strip()

    node = _first(_NODE, rest)
    pipeline = _first(_PIPELINE, rest)
    dataset: Optional[str] = None
    km = _KEY_PATH.match(rest)
    if km:
        path, rest = km["path"], km["msg"].strip()
        # The key the message is about ('descripton'), when it names one.
        key = _first(_UNQUOTED, rest)
        if path.startswith("pipelines/"):
            head, _, tail = path[len("pipelines/") :].partition(".nodes.")
            pipeline = pipeline or head
            if tail and not node:
                node = _strip_key(tail, key)
        else:
            dataset = _strip_key(path[len("catalog.") :], key)
    dm = _DATASET.search(rest)
    if dm:
        dataset = dm["v"] or dm["w"]

    fix = None
    sm = _SUGGESTION.search(rest)
    if sm:
        suggestion = sm["v"]
        before = rest[: sm.start()]
        quoted = [q["v"] for q in _UNQUOTED.finditer(before)]
        if quoted:
            wrong = quoted[-1]
            fix = Fix(label=f"Replace '{wrong}' with '{suggestion}'", replace=[wrong, suggestion])

    message = rest[0].upper() + rest[1:] if rest else raw
    return Problem(
        severity=severity,
        message=message,
        code=_code_for(rest),
        source=source,
        file=file,
        line=line,
        column=column,
        node=node,
        pipeline=pipeline,
        dataset=dataset,
        fix=fix,
        raw=raw,
    )


def parse_problems(
    errors: Iterable[str] = (),
    warnings: Iterable[str] = (),
    source: str = "config",
) -> List[Problem]:
    """Errors then warnings, each parsed."""
    return [parse_problem(e, "error", source) for e in errors] + [
        parse_problem(w, "warning", source) for w in warnings
    ]


def _strip_key(path: str, key: Optional[str]) -> str:
    """``silver.clean_student.descripton`` less the key ``descripton``: the owner's name."""
    return path[: -len(key) - 1] if key and path.endswith("." + key) else path


def _first(pattern: re.Pattern[str], text: str) -> Optional[str]:
    m = pattern.search(text)
    return m["v"] if m else None
