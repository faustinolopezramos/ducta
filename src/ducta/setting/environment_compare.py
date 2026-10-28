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

The project's effective configuration in every environment, side by side.

"Why does prod behave differently?" is answered by the rows where the
environments disagree. ``paths`` and ``settings`` are listed in full, so a
reader sees every value in force; for ``catalog`` and ``pipelines`` only the
leaves an environment changes are listed — the rest would be thousands of
identical rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ducta.setting.project.loader import apply_environment, read_project
from ducta.setting.utils import leaves

BASE = "base"
_FULL = ("paths", "settings")
_CHANGED_ONLY = ("catalog", "pipelines")


def _flatten(tree: Dict[str, Any], sections: Tuple[str, ...]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for section in sections:
        for path, value in leaves(tree.get(section) or {}, (section,)).items():
            out[".".join(path)] = value
    return out


def compare_environments(root: Path) -> Dict[str, Any]:
    """``{"environments": [...], "rows": [{key, values, differs, overridden}]}``."""
    located = read_project(Path(root))
    envs: List[str] = list((located.project.get("environments") or {}).keys())
    names = [BASE, *envs]
    trees = {name: apply_environment(located, None if name == BASE else name) for name in names}

    full = {name: _flatten(trees[name], _FULL) for name in names}
    rest = {name: _flatten(trees[name], _CHANGED_ONLY) for name in names}

    rows = []
    for table, only_changed in ((full, False), (rest, True)):
        keys: List[str] = []
        for name in names:
            keys += [k for k in table[name] if k not in keys]
        for key in sorted(keys):
            values: Dict[str, Optional[Any]] = {name: table[name].get(key) for name in names}
            base = values[BASE]
            overridden = {name: values[name] != base for name in envs}
            differs = any(overridden.values())
            if only_changed and not differs:
                continue
            rows.append(
                {"key": key, "values": values, "differs": differs, "overridden": overridden}
            )
    return {"environments": names, "rows": rows}
