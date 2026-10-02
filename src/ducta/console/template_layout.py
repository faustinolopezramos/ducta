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

The split project layout: ``catalog/<layer>.yaml`` and ``quality/profiles.yaml``.

Templates are written once, as one ``catalog.yaml`` and one ``ducta.yaml`` with
explanatory comments. This module cuts those texts into the split layout
without going through a parser, so the comments survive: a dataset keeps the
comment lines directly above it, and the profiles block keeps its own.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

#: A top-level key: a name (or quoted name) at column 0 followed by ``:``.
_KEY = re.compile(r"""^(?P<key>"[^"]+"|'[^']+'|[^\s#'"][^:\s]*):(\s|$)""")
_SCHEMA_LINE = re.compile(r"^#\s*yaml-language-server:.*$")
_PROFILES = re.compile(r"^(?P<indent>\s+)profiles:\s*$")
_QUALITY = re.compile(r"^(?P<indent>\s+)quality:\s*$")

#: Datasets with no ``layer.`` prefix (a seed CSV, a source) are filed here.
UNLAYERED = "sources"


def layer_of(dataset: str) -> str:
    """``silver`` for ``silver.sales.orders``; ``sources`` for a name with no layer."""
    return dataset.split(".", 1)[0] if "." in dataset else UNLAYERED


def split_catalog(text: str) -> Optional[Dict[str, str]]:
    """Cut a catalog's YAML text into ``{layer: text}``, keeping each dataset's comments.

    The layers keep the order in which they first appear. Returns ``None`` when the
    catalog declares no dataset (``{}``): there is nothing to split.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if _KEY.match(line)]
    if not starts:
        return None
    # A dataset owns the column-0 comment lines directly above it.
    begins: List[int] = []
    for n, start in enumerate(starts):
        floor = starts[n - 1] + 1 if n else 0
        begin = start
        while begin > floor and lines[begin - 1].startswith("#"):
            begin -= 1
        begins.append(begin)
    preface = [line for line in lines[: begins[0]] if not _SCHEMA_LINE.match(line)]
    layers: Dict[str, List[str]] = {}
    for n, begin in enumerate(begins):
        end = begins[n + 1] if n + 1 < len(begins) else len(lines)
        chunk = lines[begin:end]
        while chunk and not chunk[-1].strip():
            chunk.pop()
        name = _KEY.match(lines[starts[n]]).group("key").strip("\"'")  # type: ignore[union-attr]
        layers.setdefault(layer_of(name), []).extend([*chunk, ""])
    out: Dict[str, str] = {}
    for n, (layer, chunk) in enumerate(layers.items()):
        body = list(chunk)
        if n == 0 and any(line.strip() for line in preface):
            while preface and not preface[-1].strip():
                preface.pop()
            body = [*preface, "", *body]
        out[layer] = "\n".join(body).rstrip("\n") + "\n"
    return out


def with_schema(text: str, schema: str) -> str:
    """``text`` under a ``yaml-language-server`` line pointing at ``schema``."""
    return f"# yaml-language-server: $schema={schema}\n{text}"


def extract_profiles(project_text: str) -> Tuple[str, Optional[str]]:
    """Take ``settings.quality.profiles`` out of a ``ducta.yaml`` text.

    Returns ``(ducta.yaml text without the profiles, text of the profiles file)``; the
    second is ``None`` when the project declares no profile. A ``quality:`` block left
    with nothing but comments is replaced by a comment pointing at the new file, so
    ``quality`` never becomes an empty value.
    """
    lines = project_text.splitlines()
    at = next((i for i, line in enumerate(lines) if _PROFILES.match(line)), None)
    if at is None:
        return project_text, None
    indent = len(_PROFILES.match(lines[at]).group("indent"))  # type: ignore[union-attr]
    end = at + 1
    while end < len(lines) and (not lines[end].strip() or _indent(lines[end]) > indent):
        end += 1
    block = lines[at + 1 : end]
    while block and not block[-1].strip():
        block.pop()
    cut = indent + 2
    profiles = "\n".join(line[cut:] if line.strip() else "" for line in block) + "\n"
    rest = lines[:at] + ([""] if lines[end - 1].strip() == "" else []) + lines[end:]

    q = next((i for i, line in enumerate(rest) if _QUALITY.match(line)), None)
    if q is not None:
        q_indent = len(_QUALITY.match(rest[q]).group("indent"))  # type: ignore[union-attr]
        stop = q + 1
        while stop < len(rest) and (not rest[stop].strip() or _indent(rest[stop]) > q_indent):
            stop += 1
        inner = [line for line in rest[q + 1 : stop] if line.strip()]
        if all(line.lstrip().startswith("#") for line in inner):
            pad = " " * q_indent
            note = [
                f"{pad}# Quality profiles (reusable named sets of checks) are in quality/profiles.yaml.",
                f"{pad}# Your own @register_check modules go here: quality: {{extensions: [...]}}",
            ]
            rest = rest[:q] + note + rest[stop:]
    return "\n".join(rest) + "\n", profiles


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())
