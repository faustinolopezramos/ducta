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

Where a project's run certificates are, per environment — shared by the
certificate routes and by staleness, which compares the project with its
last successful run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from loguru import logger

from ducta.api.execution.runner import normalize_execution_context_paths, select_execution_cwd
from ducta.api.workspace.manager import WorkspaceManager
from ducta.core.certificate import iter_certificate_dirs, load_certificate
from ducta.core.settings import CoreSettings
from ducta.setting.environments import DEFAULT_ENVIRONMENTS

#: Pre-convention default, relative to the project directory. Kept discoverable
#: (read-only) so certificates written before the storage convention moved
#: run_certificate_dir under ${output_path}/${environment} don't disappear.
_LEGACY_RUNS_DIR = Path(".ducta") / "runs"


def env_runs_dir(project_dir: Path, env: str) -> Optional[Path]:
    """The run-certificates directory a run in *env* writes to, or None.

    Resolved the way the runner resolves it before executing
    (execution/runner.py): same context loader, same execution cwd, same path
    normalisation — so the ``${output_path}/${environment}/.ducta/runs``
    template lands on the directory the executor actually wrote. Nothing here
    calls ``os.chdir``: it runs inside the server process.
    """
    try:
        ctx = WorkspaceManager(project_dir).load_context(env)
    except Exception as exc:  # noqa: BLE001 — an environment the project can't load is skipped
        logger.debug("Could not resolve run-certificates dir for env '{}': {}", env, exc)
        return None
    env_dir = project_dir / env if (project_dir / env).is_dir() else project_dir
    execution_cwd = select_execution_cwd(project_dir, env_dir, ctx)
    normalize_execution_context_paths(ctx, execution_cwd)
    runs_dir = Path(CoreSettings.from_context(ctx).run_certificate_dir)
    return runs_dir if runs_dir.is_absolute() else execution_cwd / runs_dir


def candidate_runs_dirs(project_dir: Path, env: Optional[str]) -> List[Tuple[Optional[str], Path]]:
    """``[(env, runs_dir), ...]`` to search: each environment's own directory
    that exists (only *env* when given), then the legacy directory — labelled
    ``None`` because its layout may itself nest several environments."""
    dirs: List[Tuple[Optional[str], Path]] = []
    seen: set = set()
    for candidate_env in [env] if env else DEFAULT_ENVIRONMENTS:
        runs_dir = env_runs_dir(project_dir, candidate_env)
        if runs_dir is not None and runs_dir.is_dir() and runs_dir not in seen:
            seen.add(runs_dir)
            dirs.append((candidate_env, runs_dir))
    legacy = project_dir / _LEGACY_RUNS_DIR
    if legacy.is_dir():
        dirs.append((None, legacy))
    return dirs


def certificates(
    project_dir: Path, env: Optional[str]
) -> Iterator[Tuple[Optional[str], Dict[str, Any]]]:
    """Every readable certificate of the project (in *env* when given), as ``(env, data)``."""
    for dir_env, runs_dir in candidate_runs_dirs(project_dir, env):
        for found_env, _run_id, run_dir in iter_certificate_dirs(runs_dir):
            run_env = dir_env or found_env
            if env is not None and run_env != env:
                continue
            try:
                yield run_env, load_certificate(run_dir / "certificate.json")
            except Exception:  # noqa: BLE001 — a corrupt file is skipped, not fatal
                continue


def latest_successful(project_dir: Path, env: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """The newest successful certificate of each pipeline."""
    out: Dict[str, Dict[str, Any]] = {}
    for _env, data in certificates(project_dir, env):
        if str(data.get("status")) != "success":
            continue
        pipeline = str(data.get("pipeline", ""))
        if not pipeline:
            continue
        if pipeline not in out or (data.get("started_at") or "") > (
            out[pipeline].get("started_at") or ""
        ):
            out[pipeline] = data
    return out
