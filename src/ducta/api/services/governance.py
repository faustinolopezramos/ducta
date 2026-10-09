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

Governance: who may run where, and what a project expects of itself.

* Protected environments (``governance.protected_environments``, prod by
  default) take the ``pipeline.execute.protected`` permission — operators and
  admins have it, developers do not. The API enforces it; the UI only reflects it.
* Governance warnings — a pipeline or a shared dataset with no owner, a
  dataset other pipelines read with no quality contract — are reported with
  the project's other problems, and each can be turned off per project.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from ducta.setting.problems import Problem

PROTECTED_PERMISSION = "pipeline.execute.protected"
DEFAULT_PROTECTED = ("prod", "production")


def protected_environments(project_root: Optional[Path]) -> List[str]:
    """The project's protected environments; the defaults when it cannot be read."""
    if project_root is None:
        return list(DEFAULT_PROTECTED)
    try:
        from ducta.setting.project_loader import validate_project

        return list(validate_project(Path(project_root)).project.governance.protected_environments)
    except Exception:  # noqa: BLE001 — a broken project is still guarded by the defaults
        return list(DEFAULT_PROTECTED)


def check_can_run(user: Any, env: str, project_root: Optional[Path]) -> None:
    """Raise 403 when *user* may not run in *env*."""
    from fastapi import HTTPException

    if env in protected_environments(project_root) and not user.has_permission(
        PROTECTED_PERMISSION
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                f"'{env}' is a protected environment: running there takes the "
                f"'{PROTECTED_PERMISSION}' permission (operator or admin)"
            ),
        )


def governance_problems(project: Any) -> List[Problem]:
    """Missing owners and contracts, as warnings the Problems panel lists."""
    settings = project.project.governance.warnings
    out: List[Problem] = []
    readers: dict[str, set[str]] = {}
    writers: dict[str, str] = {}
    for pname, pipeline in project.pipelines.items():
        for node in pipeline.nodes.values():
            raw = getattr(node, "inputs", None) or {}
            for ds in raw.values() if isinstance(raw, dict) else raw:
                readers.setdefault(str(ds), set()).add(pname)
            for ds in getattr(node, "outputs", None) or []:
                writers[str(ds)] = pname
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
        shared = readers.get(ds, set()) - {pname}
        entry = project.catalog.get(ds)
        if not shared or entry is None:
            continue
        if settings.missing_owner and not (entry.metadata or {}).get("owner"):
            out.append(
                Problem(
                    severity="info",
                    code="governance.missing_owner",
                    message=f"Dataset '{ds}' is read by {', '.join(sorted(shared))} but has no owner",
                    dataset=ds,
                    source="governance",
                )
            )
        if settings.missing_contract and entry.quality is None:
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
    return out
