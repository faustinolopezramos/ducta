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

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from ducta.api.dependencies import (
    CurrentUserDep,
    ExecutionManagerDep,
    SourcePathDep,
    WorkspaceManagerDep,
    require_permission,
)
from ducta.api.execution.runner import normalize_execution_context_paths, select_execution_cwd
from ducta.api.models.execution import ExecutionResponse
from ducta.api.workspace.manager import WorkspaceManager
from ducta.core.certificate import (
    diff_certificates,
    find_certificate_dir,
    iter_certificate_dirs,
    load_certificate,
    resolve_signing_key_from_dir,
    verify_certificate,
)
from ducta.core.settings import CoreSettings
from ducta.setting.environments import DEFAULT_ENVIRONMENTS

router = APIRouter(prefix="/projects", tags=["certificates"])


class CertificateSummary(BaseModel):
    """One row in the certificate list."""

    run_id: str
    pipeline: str
    status: str
    started_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    environment_name: Optional[str] = None
    signed: bool = False
    quality_passed: Optional[int] = Field(
        default=None, description="Checks that passed, e.g. 3 of quality_total"
    )
    quality_total: Optional[int] = Field(
        default=None, description="Total quality checks recorded on the certificate"
    )


class CertificateVerifyResponse(BaseModel):
    """Outcome of verifying a certificate (tamper + signature check)."""

    ok: bool
    run_id: Optional[str] = None
    reason: str
    signature: str = Field(
        default="unsigned",
        description="unsigned | valid | invalid | present (no key) | stripped | unverifiable",
    )


class CertificateDiffOutputRow(BaseModel):
    key: str
    in_a: bool
    in_b: bool
    #: True (same), False (differs), None = measured with different fingerprint
    #: algorithms (e.g. across a Ducta upgrade) — "not comparable", not a claim
    #: either way. See `not_comparable_reason` for why.
    match: Optional[bool]
    not_comparable_reason: Optional[str] = None


class CertificateDiffQualityRow(BaseModel):
    node: Optional[str] = None
    phase: Optional[str] = None
    passed_a: Optional[bool] = None
    passed_b: Optional[bool] = None
    errors_a: Optional[int] = None
    errors_b: Optional[int] = None
    match: bool


class CertificateDiffResponse(BaseModel):
    """Structural diff between two Run Certificates."""

    run_a: Optional[str] = None
    run_b: Optional[str] = None
    pipeline_a: Optional[str] = None
    pipeline_b: Optional[str] = None
    pipeline_match: bool
    environment_match: bool
    status_a: Optional[str] = None
    status_b: Optional[str] = None
    status_match: bool
    config_fingerprint_match: bool
    outputs: List[CertificateDiffOutputRow]
    outputs_match: bool
    #: Whether every output could be measured with a comparable fingerprint —
    #: false means at least one output's `match` is `None` ("not comparable"),
    #: so `outputs_match`/`identical` cover only what could actually be checked.
    outputs_comparable: bool = True
    quality: List[CertificateDiffQualityRow]
    identical: bool


class ReproduceRequest(BaseModel):
    """Optional date-range override for a reproduction run."""

    start_date: Optional[str] = None
    end_date: Optional[str] = None


#: Pre-convention default, relative to the project directory. Kept discoverable
#: (read-only) so certificates written before the storage convention moved
#: run_certificate_dir under ${output_path}/${environment} don't disappear.
_LEGACY_RUNS_DIR = Path(".ducta") / "runs"


def _read_certificate(path: Path) -> Dict[str, Any]:
    """Load a certificate the caller has already located; a file that exists
    but cannot be parsed is a server-side fault (500)."""
    try:
        return load_certificate(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not read certificate: {exc}") from exc


def _project_dir(root: Path, project_id: str) -> Path:
    """The directory a project's runs execute from (same rule as execute/reproduce)."""
    return WorkspaceManager(root).for_project(project_id).root


def _env_runs_dir(project_dir: Path, env: str) -> Optional[Path]:
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


def _candidate_runs_dirs(project_dir: Path, env: Optional[str]) -> List[Tuple[Optional[str], Path]]:
    """``[(env, runs_dir), ...]`` to search: each environment's own directory
    that exists (only *env* when given), then the legacy directory — labelled
    ``None`` because its layout may itself nest several environments."""
    dirs: List[Tuple[Optional[str], Path]] = []
    seen: set = set()
    for candidate_env in [env] if env else DEFAULT_ENVIRONMENTS:
        runs_dir = _env_runs_dir(project_dir, candidate_env)
        if runs_dir is not None and runs_dir.is_dir() and runs_dir not in seen:
            seen.add(runs_dir)
            dirs.append((candidate_env, runs_dir))
    legacy = project_dir / _LEGACY_RUNS_DIR
    if legacy.is_dir():
        dirs.append((None, legacy))
    return dirs


def _certificate_path(root: Path, project_id: str, run_id: str, env: Optional[str] = None) -> Path:
    for dir_env, runs_dir in _candidate_runs_dirs(_project_dir(root, project_id), env):
        # An environment's own directory already is that environment; only the
        # legacy tree can hold several, so only it is filtered by *env*.
        run_dir = find_certificate_dir(runs_dir, run_id, env=env if dir_env is None else None)
        if run_dir is not None:
            return run_dir / "certificate.json"
    raise HTTPException(
        status_code=404,
        detail=f"No certificate found for run '{run_id}' in project '{project_id}'"
        + (f" (environment '{env}')" if env else ""),
    )


@router.get(
    "/{project_id}/certificates",
    response_model=List[CertificateSummary],
    summary="List a project's Run Certificates (newest first)",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def list_certificates(
    project_id: str,
    source_path: SourcePathDep,
    manager: WorkspaceManagerDep,
    env: Optional[str] = Query(
        None, description="Restrict to one environment (default: all environments)"
    ),
) -> List[CertificateSummary]:
    summaries: List[CertificateSummary] = []
    for dir_env, runs_dir in _candidate_runs_dirs(_project_dir(manager.root, project_id), env):
        for found_env, run_id, run_dir in iter_certificate_dirs(runs_dir):
            run_env = dir_env or found_env
            if env is not None and run_env != env:
                continue
            try:
                data = load_certificate(run_dir / "certificate.json")
            except Exception:  # noqa: BLE001 — a corrupt file must not break the listing
                continue
            quality = data.get("quality", []) or []
            summaries.append(
                CertificateSummary(
                    run_id=str(data.get("run_id", run_id)),
                    pipeline=str(data.get("pipeline", "?")),
                    status=str(data.get("status", "?")),
                    started_at=data.get("started_at"),
                    duration_seconds=data.get("duration_seconds"),
                    environment_name=run_env or data.get("environment_name"),
                    signed=bool(data.get("signature")),
                    quality_passed=sum(1 for q in quality if q.get("passed")) if quality else None,
                    quality_total=len(quality) if quality else None,
                )
            )
    summaries.sort(key=lambda s: s.started_at or "", reverse=True)
    return summaries


@router.get(
    "/{project_id}/certificates/{run_id}",
    summary="Get one Run Certificate as JSON",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_certificate(
    project_id: str,
    run_id: str,
    source_path: SourcePathDep,
    manager: WorkspaceManagerDep,
    env: Optional[str] = Query(None, description="Environment the run was recorded under"),
) -> Dict[str, Any]:
    path = _certificate_path(manager.root, project_id, run_id, env=env)
    return _read_certificate(path)


@router.post(
    "/{project_id}/certificates/{run_id}/verify",
    response_model=CertificateVerifyResponse,
    summary="Verify a Run Certificate's integrity (and signature when keyed)",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def verify_certificate_endpoint(
    project_id: str,
    run_id: str,
    source_path: SourcePathDep,
    manager: WorkspaceManagerDep,
    env: Optional[str] = Query(None, description="Environment the run was recorded under"),
) -> CertificateVerifyResponse:
    path = _certificate_path(manager.root, project_id, run_id, env=env)
    signing_root = _project_dir(manager.root, project_id)
    result = verify_certificate(path, signing_key=resolve_signing_key_from_dir(signing_root))
    return CertificateVerifyResponse(
        ok=result.ok,
        run_id=result.run_id,
        reason=result.reason,
        signature=result.signature,
    )


@router.get(
    "/{project_id}/certificates/{run_id}/diff/{other_run_id}",
    response_model=CertificateDiffResponse,
    summary="Compare two Run Certificates (config, outputs, quality)",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def diff_certificates_endpoint(
    project_id: str,
    run_id: str,
    other_run_id: str,
    source_path: SourcePathDep,
    manager: WorkspaceManagerDep,
    env: Optional[str] = Query(
        None, description="Environment both runs were recorded under (default: search all)"
    ),
) -> CertificateDiffResponse:
    path_a = _certificate_path(manager.root, project_id, run_id, env=env)
    path_b = _certificate_path(manager.root, project_id, other_run_id, env=env)
    cert_a = _read_certificate(path_a)
    cert_b = _read_certificate(path_b)
    return CertificateDiffResponse(**diff_certificates(cert_a, cert_b))


@router.post(
    "/{project_id}/certificates/{run_id}/reproduce",
    response_model=ExecutionResponse,
    status_code=202,
    summary="Re-run a certificate's pipeline to test reproducibility",
    description=(
        "Starts an async execution of the certificate's pipeline/environment, the "
        "same way POST .../pipelines/{name}/execute does. Poll the returned execution "
        "(GET /executions/{id}) until it reaches a terminal status, then read its "
        "`certificate_run_id` and call the diff endpoint against the original `run_id` "
        "to compare outputs and quality."
    ),
    dependencies=[Depends(require_permission("pipeline.execute"))],
)
async def reproduce_certificate(
    project_id: str,
    run_id: str,
    body: ReproduceRequest,
    source_path: SourcePathDep,
    exec_manager: ExecutionManagerDep,
    manager: WorkspaceManagerDep,
    current_user: CurrentUserDep,
    env: Optional[str] = Query(None, description="Environment the run was recorded under"),
) -> ExecutionResponse:
    path = _certificate_path(manager.root, project_id, run_id, env=env)
    cert = _read_certificate(path)

    pipeline = cert.get("pipeline")
    if not pipeline:
        raise HTTPException(
            status_code=422,
            detail=f"Certificate '{run_id}' has no pipeline name — cannot reproduce",
        )

    exec_source = _project_dir(manager.root, project_id)

    return exec_manager.execute(
        source_path=exec_source,
        pipeline_name=str(pipeline),
        env=str(cert.get("environment_name") or "base"),
        start_date=body.start_date,
        end_date=body.end_date,
        project_id=project_id,
        user_id=current_user.id,
    )
