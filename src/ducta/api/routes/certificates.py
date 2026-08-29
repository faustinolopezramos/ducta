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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ducta.api.dependencies import (
    CurrentUserDep,
    ExecutionManagerDep,
    SourcePathDep,
    WorkspaceManagerDep,
    require_permission,
)
from ducta.api.models.execution import ExecutionResponse
from ducta.core.certificate import (
    DEFAULT_CERTIFICATE_DIR,
    diff_certificates,
    find_certificate_dir,
    iter_certificate_dirs,
    load_certificate,
    resolve_signing_key_from_dir,
    verify_certificate,
)

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
        default="unsigned", description="unsigned | valid | invalid | present (no key)"
    )


class CertificateDiffOutputRow(BaseModel):
    key: str
    in_a: bool
    in_b: bool
    match: bool


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
    quality: List[CertificateDiffQualityRow]
    identical: bool


class ReproduceRequest(BaseModel):
    """Optional date-range override for a reproduction run."""

    start_date: Optional[str] = None
    end_date: Optional[str] = None


def _project_runs_dir(root: Path, project_id: str) -> Path:
    """The runs directory for a project (same resolution the executor uses)."""
    project_dir = root / "projects" / project_id
    base = project_dir if project_dir.is_dir() else root
    return base / DEFAULT_CERTIFICATE_DIR


def _certificate_path(root: Path, project_id: str, run_id: str, env: Optional[str] = None) -> Path:
    run_dir = find_certificate_dir(_project_runs_dir(root, project_id), run_id, env=env)
    if run_dir is None:
        raise HTTPException(
            status_code=404,
            detail=f"No certificate found for run '{run_id}' in project '{project_id}'"
            + (f" (environment '{env}')" if env else ""),
        )
    return run_dir / "certificate.json"


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
    runs_dir = _project_runs_dir(manager.root, project_id)
    summaries: List[CertificateSummary] = []
    for found_env, run_id, run_dir in iter_certificate_dirs(runs_dir):
        if env is not None and found_env != env:
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
                environment_name=found_env or data.get("environment_name"),
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
    try:
        return load_certificate(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not read certificate: {exc}")


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
    project_dir = manager.root / "projects" / project_id
    signing_root = project_dir if project_dir.is_dir() else manager.root
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
    try:
        cert_a = load_certificate(path_a)
        cert_b = load_certificate(path_b)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not read certificate: {exc}")
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
    try:
        cert = load_certificate(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not read certificate: {exc}")

    pipeline = cert.get("pipeline")
    if not pipeline:
        raise HTTPException(
            status_code=422,
            detail=f"Certificate '{run_id}' has no pipeline name — cannot reproduce",
        )

    project_dir = manager.root / "projects" / project_id
    exec_source = project_dir if project_dir.is_dir() else manager.root

    return exec_manager.execute(
        source_path=exec_source,
        pipeline_name=str(pipeline),
        env=str(cert.get("environment_name") or "base"),
        start_date=body.start_date,
        end_date=body.end_date,
        project_id=project_id,
        user_id=current_user.id,
    )
