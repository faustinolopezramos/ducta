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

Edit a YAML file's text in place: comments, quoting, indentation and blank
lines are kept, and only what the edit touches changes.

A proposal (a node's checks, a dataset's description) is applied by Ducta,
not written by the model as a whole file: the model cannot change a key it was
not asked about, and the file still reads like its author wrote it.
"""

from __future__ import annotations

import io
from typing import Any, Callable

from ducta.ai.errors import AIEnvironmentError


def edit_yaml(text: str, edit: Callable[[Any], None]) -> str:
    """*text* after *edit* changed its parsed (round-trip) document."""
    try:
        from ruamel.yaml.comments import CommentedMap

        from ducta.api.repositories.v2_store import restore_blank_lines, round_trip_yaml, style_of
    except ImportError as e:  # pragma: no cover — the api extra brings ruamel
        raise AIEnvironmentError(
            "Applying a proposal needs Ducta's API extra: pip install 'ducta[api,ai]'"
        ) from e
    doc = round_trip_yaml().load(text) if text.strip() else None
    if doc is None:
        doc = CommentedMap()
    edit(doc)
    buf = io.StringIO()
    writer = round_trip_yaml(**style_of(text))
    writer.width = 4096  # a {flow: mapping} stays on its line
    writer.dump(doc, buf)
    return restore_blank_lines(text, buf.getvalue())


def mapping(value: Any) -> Any:
    """*value* as round-trip YAML (nested mappings keep their key order)."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if isinstance(value, dict):
        out = CommentedMap()
        for k, v in value.items():
            out[k] = mapping(v)
        if value and all(_short(v) for v in value.values()):
            out.fa.set_flow_style()  # {min: 1}, as people write a check's parameters
        return out
    if isinstance(value, list):
        seq = CommentedSeq(mapping(v) for v in value)
        if all(not isinstance(v, (dict, list)) for v in value):
            seq.fa.set_flow_style()  # [a, b], as people write short lists
        return seq
    return value


def _short(value: Any) -> bool:
    if isinstance(value, dict):
        return False
    if isinstance(value, list):
        return all(not isinstance(v, (dict, list)) for v in value)
    return True
