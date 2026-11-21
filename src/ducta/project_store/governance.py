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

import os
from pathlib import Path
from typing import Any, Iterable, List, Optional

from ducta.setting.problems import Problem

PROTECTED_PERMISSION = "pipeline.execute.protected"
DEFAULT_PROTECTED = ("prod", "production")

#: The environments protected whatever a project says, as a comma-separated list. Set by
#: whoever runs the server (a project file is edited by the people the protection is
#: for: a developer wrote `protected_environments: []` and ran in prod). Unset means
#: ``prod,production``; set to an empty value, only the projects' own lists count.
FLOOR_ENV = "DUCTA_PROTECTED_ENVIRONMENTS"


def floor_environments() -> List[str]:
    """The environments :data:`FLOOR_ENV` protects for every project."""
    raw = os.environ.get(FLOOR_ENV)
    if raw is None:
        return list(DEFAULT_PROTECTED)
    return [e.strip() for e in raw.split(",") if e.strip()]


def protected_environments(project_root: Optional[Path]) -> List[str]:
    """The floor (:data:`FLOOR_ENV`) plus the project's own protected environments.

    A project can add environments, never take one of the floor's away. When the project
    cannot be read, its part is the defaults.
    """
    own: List[str] = list(DEFAULT_PROTECTED)
    if project_root is not None:
        try:
            from ducta.setting.project.loader import validate_project

            project = validate_project(Path(project_root)).project
            own = list(project.governance.protected_environments)
        except Exception:  # noqa: BLE001 — a broken project is still guarded by the defaults
            own = list(DEFAULT_PROTECTED)
    return with_floor(own)


def with_floor(own: List[str]) -> List[str]:
    """*own* with the floor's environments added (order kept, no repeats)."""
    return list(dict.fromkeys([*floor_environments(), *own]))


def canonical_environment(env: str) -> str:
    """*env* as the configuration reads it: lower case, aliases mapped (``PROD``,
    ``Production`` → ``prod``)."""
    from ducta.setting.environments import normalize_environment

    return normalize_environment(str(env)) or str(env).strip().lower()


def _names(env: str) -> set[str]:
    """The environment blocks the configuration applies to *env*: its own and, for
    ``sandbox_<dev>``, ``sandbox``'s."""
    from ducta.setting.environments import get_base_environment

    name = canonical_environment(env)
    return {name, get_base_environment(name)}


def is_protected(
    env: Optional[str],
    project_root: Optional[Path] = None,
    protected: Optional[Iterable[str]] = None,
) -> bool:
    """Whether *env* is a protected environment, compared as the configuration reads it.

    A plain ``env in protected_environments(...)`` let ``PROD`` through while the
    configuration applied the ``prod`` block to it: a developer ran with prod's settings
    and read prod's rows. *protected* defaults to :func:`protected_environments`.
    """
    if not env:
        return False
    names = protected if protected is not None else protected_environments(project_root)
    return bool(_names(env) & {canonical_environment(p) for p in names if p})


def governance_problems(project: Any) -> List[Problem]:
    """Missing owners and contracts, and ``metadata.pii`` that protects nothing, as the
    warnings the Problems panel and ``ducta check`` list."""
    settings = project.project.governance.warnings
    out: List[Problem] = []
    readers: dict[str, set[str]] = {}
    writers: dict[str, str] = {}
    #: output dataset -> the datasets the nodes writing it read.
    built_from: dict[str, set[str]] = {}
    for pname, pipeline in project.pipelines.items():
        for node in pipeline.nodes.values():
            raw = getattr(node, "inputs", None) or {}
            inputs = [str(ds) for ds in (raw.values() if isinstance(raw, dict) else raw)]
            for ds in inputs:
                readers.setdefault(ds, set()).add(pname)
            for ds in getattr(node, "outputs", None) or []:
                writers[str(ds)] = pname
                built_from.setdefault(str(ds), set()).update(inputs)
        if settings.missing_owner and not (pipeline.metadata or {}).get("owner"):
            out.append(
                Problem(
                    severity="info",
                    code="governance.missing_owner",
                    message=f"Pipeline '{pname}' has no owner (metadata.owner) — "
                    "who is told when it fails?",
                    pipeline=pname,
                    source="governance",
                )
            )
    for ds, pname in sorted(writers.items()):
        readers_of = readers.get(ds, set())
        shared = readers_of - {pname}
        entry = project.catalog.get(ds)
        if entry is None:
            continue
        # An output is what leaves its pipeline: read by another one, or by none here
        # (a gold table a dashboard reads). A step read only within its own pipeline is not.
        if (
            (shared or not readers_of)
            and settings.missing_owner
            and not (entry.metadata or {}).get("owner")
        ):
            out.append(
                Problem(
                    severity="info",
                    code="governance.missing_owner",
                    message=(
                        f"Dataset '{ds}' is read by {', '.join(sorted(shared))} but has no owner"
                        if shared
                        else f"Dataset '{ds}' is an output of '{pname}' that no pipeline here "
                        "reads (it leaves the project) and has no owner (metadata.owner)"
                    ),
                    dataset=ds,
                    source="governance",
                )
            )
        if shared and settings.missing_contract and entry.quality is None:
            out.append(
                Problem(
                    severity="info",
                    code="governance.missing_contract",
                    message=f"Dataset '{ds}' is read by {', '.join(sorted(shared))} with no quality "
                    "contract (a quality block on its catalog entry)",
                    dataset=ds,
                    source="governance",
                )
            )
    if getattr(settings, "pii", True):
        out += _pii_problems(project, built_from)
    return out


def _pii_of(entry: Any) -> Optional[List[str]]:
    """The entry's ``metadata.pii`` list, or ``None`` when it does not say."""
    metadata = getattr(entry, "metadata", None) or {}
    if not isinstance(metadata, dict) or "pii" not in metadata:
        return None
    return [str(c) for c in metadata.get("pii") or [] if c]


def known_columns(entry: Any) -> List[str]:
    """The columns a catalog entry states without reading data: its ``schema`` (DDL) and
    the ``expected_columns`` of its contract's schema check. Empty when it states none."""
    found: List[str] = []
    ddl = getattr(entry, "schema_def", None)
    if isinstance(ddl, str) and ddl.strip():
        depth, part, parts = 0, "", []
        for ch in ddl:
            if ch in "<(":
                depth += 1
            elif ch in ">)":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(part)
                part = ""
            else:
                part += ch
        parts.append(part)
        for p in parts:
            p = p.strip()
            quote = p[:1]
            if quote in ("`", '"') and quote in p[1:]:
                found.append(p[1 : p.index(quote, 1)])  # a quoted name may hold spaces
            elif p:
                found.append(p.split(None, 1)[0].rstrip(":"))
    quality = getattr(entry, "quality", None)
    checks = getattr(quality, "checks", None) if quality is not None else None
    for name, params in (checks or {}).items() if isinstance(checks, dict) else []:
        if isinstance(params, dict) and (params.get("type") or name) == "schema":
            found += [str(c) for c in params.get("expected_columns") or []]
    return list(dict.fromkeys(c for c in found if c))


def _pii_problems(project: Any, built_from: dict[str, set[str]]) -> List[Problem]:
    out: List[Problem] = []
    for ds, entry in sorted(project.catalog.items()):
        pii = _pii_of(entry)
        known = {c.lower() for c in known_columns(entry)}
        unknown = [c for c in pii or [] if known and c.lower() not in known]
        if unknown:
            out.append(
                Problem(
                    severity="warning",
                    code="governance.pii_unknown_column",
                    message=f"Dataset '{ds}' lists {', '.join(unknown)} in metadata.pii, not a "
                    f"column it states ({', '.join(sorted(known))}): a misspelt name masks nothing",
                    dataset=ds,
                    source="governance",
                )
            )
    for ds, sources in sorted(built_from.items()):
        entry = project.catalog.get(ds)
        if entry is None or _pii_of(entry) is not None:
            continue
        personal = sorted(s for s in sources if _pii_of(project.catalog.get(s)))
        if personal:
            out.append(
                Problem(
                    severity="info",
                    code="governance.pii_downstream",
                    message=f"Dataset '{ds}' is built from {', '.join(personal)}, which hold(s) "
                    "personal data, and says nothing of its own: list its metadata.pii "
                    "columns (masked like theirs), or `pii: []` if it keeps none",
                    dataset=ds,
                    source="governance",
                )
            )
    return out
