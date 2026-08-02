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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ducta.api.dependencies import SourcePathDep, WorkspaceManagerDep, require_permission
from ducta.core.certificate import (
    DEFAULT_CERTIFICATE_DIR,
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


class CertificateVerifyResponse(BaseModel):
    """Outcome of verifying a certificate (tamper + signature check)."""

    ok: bool
    run_id: Optional[str] = None
    reason: str
    signature: str = Field(
        default="unsigned", description="unsigned | valid | invalid | present (no key)"
    )


def _project_runs_dir(root: Path, project_id: str) -> Path:
    """The runs directory for a project (same resolution the executor uses)."""
    project_dir = root / "projects" / project_id
    base = project_dir if project_dir.is_dir() else root
    return base / DEFAULT_CERTIFICATE_DIR


def _certificate_path(root: Path, project_id: str, run_id: str) -> Path:
    path = _project_runs_dir(root, project_id) / run_id / "certificate.json"
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"No certificate found for run '{run_id}' in project '{project_id}'",
        )
    return path


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
) -> List[CertificateSummary]:
    runs_dir = _project_runs_dir(manager.root, project_id)
    summaries: List[CertificateSummary] = []
    if not runs_dir.is_dir():
        return summaries
    for path in runs_dir.glob("*/certificate.json"):
        try:
            data = load_certificate(path)
        except Exception:  # noqa: BLE001 — a corrupt file must not break the listing
            continue
        summaries.append(
            CertificateSummary(
                run_id=str(data.get("run_id", path.parent.name)),
                pipeline=str(data.get("pipeline", "?")),
                status=str(data.get("status", "?")),
                started_at=data.get("started_at"),
                duration_seconds=data.get("duration_seconds"),
                environment_name=data.get("environment_name"),
                signed=bool(data.get("signature")),
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
) -> Dict[str, Any]:
    path = _certificate_path(manager.root, project_id, run_id)
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
) -> CertificateVerifyResponse:
    path = _certificate_path(manager.root, project_id, run_id)
    project_dir = manager.root / "projects" / project_id
    signing_root = project_dir if project_dir.is_dir() else manager.root
    result = verify_certificate(path, signing_key=resolve_signing_key_from_dir(signing_root))
    return CertificateVerifyResponse(
        ok=result.ok,
        run_id=result.run_id,
        reason=result.reason,
        signature=result.signature,
    )
