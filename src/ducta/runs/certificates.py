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

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from loguru import logger

from ducta.core.certificate import candidate_runs_dirs as shared_candidate_runs_dirs
from ducta.core.certificate import (
    find_certificate_dir,
    iter_certificate_dirs,
    load_certificate,
    search_environments,
)
from ducta.core.settings import CoreSettings
from ducta.runs.context import (
    load_project_context,
    normalize_execution_context_paths,
    select_execution_cwd,
)


def _env_context(project_dir: Path, env: str) -> Optional[Tuple[Any, Path]]:
    """``(context, execution_cwd)`` of *env*, resolved the way the runner resolves
    them before executing (execution/runner.py): same context loader, same execution
    cwd, same path normalisation. Nothing here calls ``os.chdir``: it runs inside
    the server process."""
    try:
        ctx = load_project_context(project_dir, env)
    except Exception as exc:  # noqa: BLE001 — an environment the project can't load is skipped
        logger.debug("Could not load the context of env '{}': {}", env, exc)
        return None
    env_dir = project_dir / env if (project_dir / env).is_dir() else project_dir
    execution_cwd = select_execution_cwd(project_dir, env_dir, ctx)
    normalize_execution_context_paths(ctx, execution_cwd)
    return ctx, execution_cwd


def env_stream_journal_dir(project_dir: Path, env: str) -> Optional[Path]:
    """Where a streaming run in *env* journals itself (ducta.stream.journal), or None."""
    from ducta.stream.journal import journal_base

    loaded = _env_context(project_dir, env)
    if loaded is None:
        return None
    ctx, execution_cwd = loaded
    base = journal_base(ctx)
    if base is None:
        return None
    return Path(base) if Path(base).is_absolute() else execution_cwd / base


def _configured_runs_dir(project_dir: Path, env: str) -> Optional[Path]:
    """*env*'s ``run_certificate_dir`` as configured, still relative when it is:
    ``candidate_runs_dirs`` decides which directories it may be relative to."""
    try:
        ctx = load_project_context(project_dir, env)
    except Exception as exc:  # noqa: BLE001 — an environment the project can't load is skipped
        logger.debug("Could not load the context of env '{}': {}", env, exc)
        return None
    return Path(CoreSettings.from_context(ctx).run_certificate_dir)


def candidate_runs_dirs(project_dir: Path, env: Optional[str]) -> List[Tuple[Optional[str], Path]]:
    """``[(env, runs_dir), ...]`` to search — the same directories ``ducta certify``
    searches (see ``ducta.core.certificate.candidate_runs_dirs``)."""
    envs = [env] if env else search_environments(project_dir)
    return shared_candidate_runs_dirs(
        project_dir, envs, lambda e: _configured_runs_dir(project_dir, e)
    )


def certificates(
    project_dir: Path, env: Optional[str]
) -> Iterator[Tuple[Optional[str], Dict[str, Any]]]:
    """Every readable certificate of the project (in *env* when given), as ``(env, data)``."""
    for dir_env, runs_dir in candidate_runs_dirs(project_dir, env):
        for _run_id, run_dir in iter_certificate_dirs(runs_dir):
            try:
                yield dir_env, load_certificate(run_dir / "certificate.json")
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


def _owns_pipeline(project_dir: Path, pipeline: str) -> bool:
    """Whether *project_dir* declares a pipeline called *pipeline*."""
    pipelines = project_dir / "pipelines"
    return (
        bool(pipeline)
        and pipelines.is_dir()
        and any(p.stem == pipeline for p in pipelines.rglob("*") if p.suffix in (".yaml", ".yml"))
    )


def mirrored_certificate(project_dir: Path, run_id: str) -> Optional[Dict[str, Any]]:
    """The copy of *run_id*'s certificate that ``write_certificate`` mirrors to the
    StorageBackend, when it belongs to this project — or None.
    """
    try:
        from ducta.core.storage import get_storage_backend

        raw = get_storage_backend().get_object(f"certificates/{run_id}/certificate.json")
        data: Dict[str, Any] = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001 — absent or unreadable mirror: nothing to offer
        return None
    return data if _owns_pipeline(project_dir, str(data.get("pipeline") or "")) else None


def load_run_certificate(
    project_dir: Path, run_id: str, env: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """*run_id*'s certificate: the project's own copy first, then the mirror."""
    for _env, runs_dir in candidate_runs_dirs(project_dir, env):
        run_dir = find_certificate_dir(runs_dir, run_id)
        if run_dir is not None:
            return load_certificate(run_dir / "certificate.json")
    data = mirrored_certificate(project_dir, run_id)
    if data is not None and env is not None and data.get("environment_name") not in (None, env):
        return None
    return data
