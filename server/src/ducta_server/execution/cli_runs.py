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

Runs the server did not start, read from their Run Certificates.

``ducta start`` (the CLI) writes a certificate for every run but no server
record. The run history listed only server records, so a project run from the
terminal looked as if it had never run in Runs, Certificates and the project
cards, while Health (which reads certificates) showed the same runs.

Each certificate becomes an :class:`ExecutionResponse` with ``origin="cli"``.
Reading every certificate on each poll would be wasteful, so a runs directory
is parsed again only when its entries change (mtime + count), and the list of
runs directories of a project (it needs the project's configuration) is kept
for a short while.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ducta_server.models.execution import ExecutionResponse, ExecutionStatus

# Finding the runs directories loads the project configuration (~0.3 s); they
# change only with that configuration.
_DIRS_TTL_SECONDS = 300.0

_STATUS = {
    "success": ExecutionStatus.SUCCESS,
    "failed": ExecutionStatus.FAILED,
    "skipped": ExecutionStatus.SKIPPED,
    "gate_blocked": ExecutionStatus.GATE_BLOCKED,
    "cancelled": ExecutionStatus.CANCELLED,
    "interrupted": ExecutionStatus.INTERRUPTED,
    # A certificate still saying "running" was never finished by its process.
    "running": ExecutionStatus.INTERRUPTED,
}

_lock = threading.Lock()
#: project_dir -> (read at, [(env, runs_dir)])
_dirs_cache: Dict[str, Tuple[float, List[Tuple[Optional[str], Path]]]] = {}
#: runs_dir -> (signature, [record data])
_runs_cache: Dict[str, Tuple[Tuple[float, int], List[Dict[str, Any]]]] = {}


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _runs_dirs(project_dir: Path) -> List[Tuple[Optional[str], Path]]:
    key = str(project_dir)
    now = time.monotonic()
    with _lock:
        cached = _dirs_cache.get(key)
        if cached and now - cached[0] < _DIRS_TTL_SECONDS:
            return cached[1]
    from ducta.runs.certificates import candidate_runs_dirs

    try:
        dirs = candidate_runs_dirs(project_dir, None)
    except Exception as exc:  # noqa: BLE001 — a project that does not load lists no CLI runs
        logger.debug("CLI runs: no runs dirs for {p}: {e}", p=project_dir, e=exc)
        dirs = []
    with _lock:
        _dirs_cache[key] = (now, dirs)
    return dirs


def _signature(runs_dir: Path) -> Optional[Tuple[float, int]]:
    try:
        return (runs_dir.stat().st_mtime, sum(1 for _ in runs_dir.iterdir()))
    except OSError:
        return None


def _read_dir(env: Optional[str], runs_dir: Path) -> List[Dict[str, Any]]:
    signature = _signature(runs_dir)
    if signature is None:
        return []
    key = str(runs_dir)
    with _lock:
        cached = _runs_cache.get(key)
        if cached and cached[0] == signature:
            return cached[1]
    from ducta.core.certificate import iter_certificate_dirs, load_certificate

    rows: List[Dict[str, Any]] = []
    for run_id, run_dir in iter_certificate_dirs(runs_dir):
        try:
            data = load_certificate(run_dir / "certificate.json")
        except Exception:  # noqa: BLE001 — a corrupt certificate is skipped, not fatal
            continue
        rows.append(
            {
                "run_id": str(data.get("run_id") or run_id),
                "pipeline": str(data.get("pipeline") or "?"),
                "status": str(data.get("status") or ""),
                "env": env or str(data.get("environment_name") or "base"),
                "started_at": data.get("started_at"),
                "ended_at": data.get("ended_at"),
                "duration_seconds": data.get("duration_seconds"),
                "error": data.get("error"),
            }
        )
    with _lock:
        _runs_cache[key] = (signature, rows)
    return rows


def _error_text(error: Any) -> Optional[str]:
    if not error:
        return None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or error)
    return str(error)


def project_cli_runs(
    project_id: str, project_dir: Path, workspace: Path
) -> List[ExecutionResponse]:
    """Every certificate of the project as a run record (origin ``cli``)."""
    out: List[ExecutionResponse] = []
    seen: set[str] = set()
    for env, runs_dir in _runs_dirs(project_dir):
        for row in _read_dir(env, runs_dir):
            if row["run_id"] in seen:
                continue
            seen.add(row["run_id"])
            try:
                out.append(
                    ExecutionResponse(
                        id=row["run_id"],
                        pipeline_name=row["pipeline"],
                        project_id=project_id,
                        env=row["env"],
                        status=_STATUS.get(row["status"], ExecutionStatus.FAILED),
                        started_at=_parse_time(row["started_at"]),
                        finished_at=_parse_time(row["ended_at"]),
                        duration_seconds=row["duration_seconds"],
                        error_message=_error_text(row["error"]),
                        certificate_run_id=row["run_id"],
                        workspace=str(workspace),
                        origin="cli",
                    )
                )
            except ValueError:  # an environment name the model rejects: skip the row
                continue
    return out


def workspace_cli_runs(workspace: Path, known_certificates: set[str]) -> List[ExecutionResponse]:
    """The CLI runs of every project in *workspace* the server has no record of."""
    from ducta_server.repositories.project_repository import ProjectRepository

    try:
        repo = ProjectRepository(Path(workspace))
        ids = repo.list_ids()
    except Exception:  # noqa: BLE001
        return []
    runs: List[ExecutionResponse] = []
    for project_id in ids:
        try:
            project_dir = repo.project_dir(project_id)
        except Exception:  # noqa: BLE001
            continue
        runs.extend(
            r
            for r in project_cli_runs(project_id, project_dir, Path(workspace))
            if r.id not in known_certificates
        )
    return runs


def clear_cache() -> None:
    """Forget every cached directory (tests)."""
    with _lock:
        _dirs_cache.clear()
        _runs_cache.clear()
