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

Who may see a dataset's rows through the API (preview, failing rows, stream
sink rows, trying checks), and which values they see.

* Rows of a **protected environment** (``governance.protected_environments``,
  ``prod`` by default) take :data:`READ_PROTECTED` — the operator's and the
  admin's, like running there.
* Columns a dataset lists in ``metadata.pii`` are masked for whoever lacks
  :data:`READ_PII` (the developer's and the admin's), and a rule or check that
  names one of them is refused for them: its count of failing rows would tell
  the values one guess at a time.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

from ducta.project_store.governance import is_protected, protected_environments

READ_PROTECTED = "data.read.protected"
READ_PII = "data.read.pii"
#: What a masked value reads as.
MASK = "••••"

#: The sensitive reads a request was allowed (prod rows, personal data): the audit
#: middleware sets a fresh list per request and writes what the guards noted into
#: ``audit.log`` — a read leaves no trace otherwise, its request being a GET. A list, not
#: a value: a route's worker thread runs in a copy of the context, and shares the list.
DATA_READS: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar(
    "ducta_data_reads", default=None
)


def note_read(kind: str, **detail: Any) -> None:
    """Record one allowed sensitive read for this request's audit entry (no-op outside one)."""
    reads = DATA_READS.get()
    if reads is not None and len(reads) < 50:
        entry = {"kind": kind, **{k: v for k, v in detail.items() if v is not None}}
        if entry not in reads:
            reads.append(entry)


def check_can_read_rows(user: Any, env: str, project_root: Optional[Path]) -> None:
    """Raise 403 when *user* may not see rows of *env*."""
    from fastapi import HTTPException

    if not is_protected(env, project_root):
        return
    if user is not None and not user.has_permission(READ_PROTECTED):
        raise HTTPException(
            status_code=403,
            detail=(
                f"'{env}' is a protected environment: its rows take the "
                f"'{READ_PROTECTED}' permission (operator or admin)"
            ),
        )
    note_read("protected_rows", env=env)


def pii_columns(project_root: Path, env: str, dataset: str) -> Set[str]:
    """The columns *dataset* lists in ``metadata.pii`` (lower-cased; empty when none)."""
    try:
        from ducta.setting.project.loader import validate_project

        project = validate_project(Path(project_root), env)
        entry = (getattr(project, "catalog", None) or {}).get(dataset)
        metadata = getattr(entry, "metadata", None) if entry is not None else None
    except Exception:  # noqa: BLE001 — an unreadable project: the caller already failed on it
        metadata = None
    items = (metadata or {}).get("pii") if isinstance(metadata, dict) else None
    return {str(c).lower() for c in items or [] if c}


def hidden_columns(user: Any, project_root: Path, env: str, dataset: str) -> Set[str]:
    """The PII columns *user* must not see the values of (empty with :data:`READ_PII`)."""
    if user is None:
        return set()
    if user.has_permission(READ_PII):
        if DATA_READS.get() is not None:
            shown = pii_columns(project_root, env, dataset)
            if shown:
                note_read("pii", env=env, dataset=dataset, columns=sorted(shown))
        return set()
    return pii_columns(project_root, env, dataset)


def mask_rows(rows: List[Dict[str, Any]], hidden: Set[str]) -> List[Dict[str, Any]]:
    """*rows* with the values of the *hidden* columns replaced by :data:`MASK` (nulls stay null)."""
    if not hidden:
        return rows
    return [
        {k: (MASK if str(k).lower() in hidden and v is not None else v) for k, v in row.items()}
        for row in rows
    ]


def names_in(config: Any) -> Set[str]:
    """Every word in *config* (keys, strings, nested): the columns a check or rule may name.

    Deliberately broad: a string literal that happens to equal a PII column's name counts
    too, which only ever refuses more.
    """
    found: Set[str] = set()
    if isinstance(config, dict):
        for k, v in config.items():
            found |= names_in(k) | names_in(v)
    elif isinstance(config, (list, tuple, set)):
        for v in config:
            found |= names_in(v)
    elif isinstance(config, str):
        # Words in any script: an ASCII-only pattern split `teléfono` into `tel` and
        # `fono`, and a rule on it went through. The whole string and every quoted
        # identifier count too, for names a word cannot hold (`fecha nacimiento`).
        found |= set(_WORD.findall(config))
        found |= {a or b for a, b in _QUOTED.findall(config) if a or b}
        found.add(config.strip())
    return found


#: A word in any script (``\w`` is Unicode on ``str``).
_WORD = re.compile(r"\w+")
#: What goes between backticks or double quotes: a quoted identifier.
_QUOTED = re.compile(r"`([^`]*)`|\"([^\"]*)\"")


def refuse_hidden(used: Iterable[str], hidden: Set[str]) -> None:
    """403 when a check or rule names a column the user may not see."""
    from fastapi import HTTPException

    named = sorted({str(c) for c in used if str(c).lower() in hidden})
    if named:
        raise HTTPException(
            status_code=403,
            detail=(
                f"{', '.join(named)} hold(s) personal data (metadata.pii): checking rows "
                f"against them takes the '{READ_PII}' permission"
            ),
        )


# ── Files that hold a protected environment's data ─────────────────────────────
#
# The preview and failing-rows routes check the environment, but the same rows sit in
# files inside the workspace: the file API, git diffs and blame served them whole to a
# viewer (prod CSV with emails and IBANs), and a developer could overwrite a prod dataset
# or its quality history through the editor. These helpers say which files those are:
# what a run in a protected environment reads or writes (``<output>/<env>/`` and every
# catalog path it resolves to), so that reading them takes :data:`READ_PROTECTED` and
# writing them :data:`WRITE_PROTECTED` (no built-in role but admin has it).

#: Changing files of a protected environment's data through the API (admins only).
WRITE_PROTECTED = "data.write.protected"


def _project_of(workspace_root: Path, target: Path) -> Optional[Path]:
    """The nearest folder from *target* up to *workspace_root* holding a ``ducta.yaml``."""
    from ducta.setting.project.reader import PROJECT_FILE

    root = workspace_root.resolve()
    for folder in [target, *target.parents]:
        if (folder / PROJECT_FILE).is_file():
            return folder
        if folder == root:
            return None
    return None


def _env_locations(project_root: Path, env: str) -> tuple[Optional[Path], List[tuple[str, Path]]]:
    """``(<output>/<env>, [(dataset, local path), ...])`` for a run of *project_root* in *env*."""
    from ducta.runs.context import (
        load_project_context,
        normalize_execution_context_paths,
        select_execution_cwd,
    )

    ctx = load_project_context(project_root, env)
    env_dir = project_root / env if (project_root / env).is_dir() else project_root
    normalize_execution_context_paths(ctx, select_execution_cwd(project_root, env_dir, ctx))
    output = (getattr(ctx, "global_config", {}) or {}).get("output_path")
    env_root = (Path(output) / env).resolve() if output and "://" not in str(output) else None
    datasets: List[tuple[str, Path]] = []
    for mapping in (getattr(ctx, "input_config", None), getattr(ctx, "output_config", None)):
        for name, entry in (mapping or {}).items():
            if not isinstance(entry, dict):
                continue
            for key in ("filepath", "path", "checkpointLocation"):
                value = entry.get(key)
                if value and "://" not in str(value):
                    datasets.append((str(name), Path(str(value)).resolve()))
    return env_root, datasets


def _env_data_paths(project_root: Path, env: str) -> List[Path]:
    """Where a run of *project_root* in *env* keeps data: ``<output>/<env>`` and catalog paths."""
    env_root, datasets = _env_locations(project_root, env)
    return ([env_root] if env_root is not None else []) + [p for _name, p in datasets]


def hidden_columns_of_file(user: Any, workspace_root: Path, rel_path: str) -> Set[str]:
    """The PII columns *user* may not see in the workspace file *rel_path*: those of every
    catalog dataset, in any environment of its project, whose data the file is (or holds)."""
    if user is None or user.has_permission(READ_PII):
        return set()
    root = Path(workspace_root).resolve()
    target = (root / rel_path).resolve()
    project = _project_of(root, target if target.is_dir() else target.parent)
    if project is None:
        return set()
    try:
        from ducta.setting.project.loader import validate_project

        envs = ["base", *validate_project(project).project.environments]
    except Exception:  # noqa: BLE001 — an unreadable project: nothing to map the file to
        return set()
    hidden: Set[str] = set()
    for env in dict.fromkeys(envs):
        try:
            _root, datasets = _env_locations(project, env)
        except Exception:  # noqa: BLE001 — one environment that does not load
            continue
        for name, path in datasets:
            if target == path or target.is_relative_to(path):
                hidden |= pii_columns(project, env, name)
    return hidden


class ProtectedData:
    """Which workspace files hold data of a protected environment (cached per project)."""

    def __init__(self, workspace_root: Path) -> None:
        self.root = Path(workspace_root).resolve()
        self._cache: Dict[Path, List[tuple[str, Optional[Path]]]] = {}

    def _roots(self, project: Path) -> List[tuple[str, Optional[Path]]]:
        """``(env, path)`` per protected env; ``(env, None)`` when the project could not be
        read for it — then any folder of the project named like the env is guarded."""
        if project not in self._cache:
            out: List[tuple[str, Optional[Path]]] = []
            for env in protected_environments(project):
                try:
                    out += [(env, p) for p in _env_data_paths(project, env)]
                except Exception:  # noqa: BLE001 — fail closed, by folder name
                    out.append((env, None))
            self._cache[project] = out
        return self._cache[project]

    def env_of(self, rel_path: str) -> Optional[str]:
        """The protected environment whose data *rel_path* is, or ``None``."""
        target = (self.root / rel_path).resolve()
        project = _project_of(self.root, target if target.is_dir() else target.parent)
        if project is None:
            return None
        folders = [p.lower() for p in target.relative_to(project).parts[:-1]]
        for env, root in self._roots(project):
            if root is None:
                if env.lower() in folders:
                    return env
            elif target == root or target.is_relative_to(root):
                return env
        return None


def refuse_protected_data(
    user: Any, workspace_root: Path, rel_path: str, *, write: bool = False
) -> None:
    """403 when *rel_path* holds a protected environment's data and *user* may not
    read it (or, with *write*, change it)."""
    from fastapi import HTTPException

    needed = WRITE_PROTECTED if write else READ_PROTECTED
    if user is None:
        return
    allowed = user.has_permission(needed)
    if allowed and (write or DATA_READS.get() is None):
        # A write is audited as one already (its method); outside a request nothing is
        # recorded. Either way, no lookup.
        return
    env = ProtectedData(workspace_root).env_of(rel_path)
    if env is not None and allowed:
        note_read("protected_file", env=env, path=rel_path)
    elif env is not None:
        raise HTTPException(
            status_code=403,
            detail=(
                f"'{rel_path}' holds data of the protected environment '{env}': "
                + ("changing it" if write else "reading it")
                + f" takes the '{needed}' permission"
            ),
        )


def hidden_data(user: Any, workspace_root: Path) -> Optional[Callable[[str], bool]]:
    """For whole-commit diffs: a test for the paths *user* may not read, or ``None``."""
    if user is None or user.has_permission(READ_PROTECTED):
        return None
    guard = ProtectedData(workspace_root)
    return lambda rel_path: guard.env_of(rel_path) is not None
