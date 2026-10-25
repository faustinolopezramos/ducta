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

Read a project's files in YAML, TOML or JSON, remembering where each key was written.

The format is only syntax: all three become the same Python mappings, and from
there the schema, the environments and the compiler are format-blind. What
differs is how precisely an error can be located. YAML and JSON give the line
of every key and list item. TOML gives the line of every key written as
``key = value`` under its ``[table]`` header; a value inside an inline table
(``{a = 1}``) or a multi-line array is located at the line of the key that holds
it.

``ducta.toml`` and ``ducta.json`` take part in discovery exactly as
``ducta.yaml`` does. A project keeps one file per role: two of the same stem
(``ducta.yaml`` and ``ducta.toml``) are an error, never a silent choice.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml  # type: ignore[import-untyped]

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

#: Every suffix a project file may have, in the order discovery lists them.
SUFFIXES: Tuple[str, ...] = (".yaml", ".yml", ".toml", ".json")

_FORMAT = {".yaml": "YAML", ".yml": "YAML", ".toml": "TOML", ".json": "JSON"}

Where = Dict[Tuple[str, ...], str]


def format_of(path: Path) -> str:
    """``YAML``, ``TOML`` or ``JSON``."""
    return _FORMAT[path.suffix.lower()]


def find_files(directory: Path, stem: str) -> List[Path]:
    """Every ``<stem>.<suffix>`` in ``directory`` (more than one is an error to report)."""
    return [
        directory / f"{stem}{ext}" for ext in SUFFIXES if (directory / f"{stem}{ext}").is_file()
    ]


def with_a_suffix(root: Path, reference: str) -> Path:
    """``root/reference`` as written, or with the first suffix that exists."""
    path = root / reference
    if path.suffix.lower() in _FORMAT:
        return path
    return next(
        (c for c in (root / f"{reference}{e}" for e in SUFFIXES) if c.is_file()),
        path.with_name(f"{path.name}.yaml"),
    )


# ── parsing ──────────────────────────────────────────────────────────────────


def parse(path: Path, text: str) -> Any:
    """The document in ``text``; ``ValueError`` (with the position) when it is not valid."""
    kind = format_of(path)
    try:
        if kind == "YAML":
            data = yaml.safe_load(text)
        elif kind == "TOML":
            data = tomllib.loads(text)
        else:
            data = json.loads(text) if text.strip() else None
    except (yaml.YAMLError, tomllib.TOMLDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"not valid {kind} — {e}") from e
    if isinstance(data, dict):
        data.pop("$schema", None)  # JSON has no comments: this is how it names its schema
    return data if data is not None else {}


def load(path: Path) -> Any:
    """Parse ``path`` without positions."""
    return parse(path, path.read_text(encoding="utf-8"))


def index(path: Path, text: str, prefix: Tuple[str, ...], where: Where, rel: str) -> None:
    """Record ``rel:line`` in ``where`` for the document's keys and list items, under ``prefix``."""
    kind = format_of(path)
    if kind == "YAML":
        node = yaml.compose(text)
        if node is not None:
            _index_yaml(node, prefix, where, rel)
    elif kind == "JSON":
        _JsonIndex(text, where, rel).value(prefix)
    else:
        _index_toml(text, prefix, where, rel)


# ── YAML ─────────────────────────────────────────────────────────────────────


def _index_yaml(node: Any, prefix: Tuple[str, ...], where: Where, rel: str) -> None:
    where.setdefault(prefix, f"{rel}:{node.start_mark.line + 1}")
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            key = (*prefix, str(key_node.value))
            where[key] = f"{rel}:{key_node.start_mark.line + 1}"
            _index_yaml(value_node, key, where, rel)
    elif isinstance(node, yaml.SequenceNode):
        for i, item in enumerate(node.value):
            _index_yaml(item, (*prefix, str(i)), where, rel)


# ── JSON ─────────────────────────────────────────────────────────────────────


class _JsonIndex:
    """A scanner over text that ``json.loads`` has already accepted."""

    def __init__(self, text: str, where: Where, rel: str) -> None:
        self.t, self.where, self.rel = text, where, rel
        self.i, self.line = 0, 1

    def _skip(self) -> None:
        while self.i < len(self.t) and self.t[self.i] in " \t\r\n":
            if self.t[self.i] == "\n":
                self.line += 1
            self.i += 1

    def _string(self) -> str:
        start = self.i
        self.i += 1
        while self.t[self.i] != '"':
            self.i += 2 if self.t[self.i] == "\\" else 1
        self.i += 1
        return str(json.loads(self.t[start : self.i]))

    def value(self, prefix: Tuple[str, ...]) -> None:
        self._skip()
        if self.i >= len(self.t):
            return
        self.where.setdefault(prefix, f"{self.rel}:{self.line}")
        char = self.t[self.i]
        if char == "{":
            self.i += 1
            while True:
                self._skip()
                if self.t[self.i] == "}":
                    self.i += 1
                    return
                line = self.line
                key = self._string()
                self._skip()
                self.i += 1  # ':'
                path = (*prefix, key)
                self.where[path] = f"{self.rel}:{line}"
                self.value(path)
                self._skip()
                if self.t[self.i] == ",":
                    self.i += 1
        elif char == "[":
            self.i += 1
            position = 0
            while True:
                self._skip()
                if self.t[self.i] == "]":
                    self.i += 1
                    return
                self.value((*prefix, str(position)))
                position += 1
                self._skip()
                if self.t[self.i] == ",":
                    self.i += 1
        elif char == '"':
            self._string()
        else:
            while self.i < len(self.t) and self.t[self.i] not in ",}] \t\r\n":
                self.i += 1


# ── TOML ─────────────────────────────────────────────────────────────────────

_TOML_HEADER = re.compile(r"^\s*(\[\[?)\s*(.+?)\s*\]\]?\s*(?:#.*)?$")
_TOML_KEY = re.compile(
    r"^\s*((?:\"(?:[^\"\\]|\\.)*\"|'[^']*'|[A-Za-z0-9_\-]+)(?:\s*\.\s*(?:\"(?:[^\"\\]|\\.)*\"|'[^']*'|[A-Za-z0-9_\-]+))*)\s*="
)
_TOML_SEGMENT = re.compile(r"\"((?:[^\"\\]|\\.)*)\"|'([^']*)'|([A-Za-z0-9_\-]+)")


def _toml_segments(dotted: str) -> List[str]:
    return [a or b or c for a, b, c in _TOML_SEGMENT.findall(dotted)]


def _register(
    where: Where, prefix: Tuple[str, ...], path: Tuple[str, ...], at: str, header: bool = False
) -> None:
    """Locate ``path``, and the tables above it that the file never names on a line of their own.

    ``[nodes.a]`` implies a ``nodes`` table; error locations are found by
    walking down from the document, so every ancestor needs an entry.
    """
    for end in range(len(prefix) + 1, len(path)):
        where.setdefault(path[:end], at)
    if header:
        where.setdefault(path, at)
    else:
        where[path] = at


def _index_toml(text: str, prefix: Tuple[str, ...], where: Where, rel: str) -> None:
    where.setdefault(prefix, f"{rel}:1")
    table: Tuple[str, ...] = prefix
    seen: Dict[Tuple[str, ...], int] = {}
    in_string = ""  # the delimiter of a multi-line string we are inside
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw
        if in_string:
            if line.count(in_string) % 2 == 1:
                in_string = ""
            continue
        header = _TOML_HEADER.match(line)
        if header:
            path = (*prefix, *_toml_segments(header.group(2)))
            if header.group(1) == "[[":
                count = seen.get(path, 0)
                seen[path] = count + 1
                path = (*path, str(count))
            table = path
            _register(where, prefix, path, f"{rel}:{number}", header=True)
            continue
        key = _TOML_KEY.match(line)
        if key:
            path = (*table, *_toml_segments(key.group(1)))
            _register(where, prefix, path, f"{rel}:{number}")
            for delimiter in ('"""', "'''"):
                if line.count(delimiter) % 2 == 1:
                    in_string = delimiter
