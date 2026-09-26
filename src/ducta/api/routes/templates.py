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

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from ducta.api.dependencies import WorkspaceManagerDep, require_permission
from ducta.api.exceptions import http_error_on
from ducta.api.models.template import (
    GenerateFromTemplateRequest,
    GenerateFromTemplateResponse,
    TemplateInfo,
)
from ducta.api.utils.validators import validate_project_name

router = APIRouter(prefix="/templates", tags=["Templates"])


@router.get(
    "",
    response_model=List[TemplateInfo],
    dependencies=[Depends(require_permission("template.read"))],
    summary="List available project templates",
)
async def list_templates() -> List[TemplateInfo]:
    from ducta.console.template import TemplateFactory

    return [TemplateInfo(**t) for t in TemplateFactory.list_available_templates()]


@router.post(
    "/generate",
    response_model=GenerateFromTemplateResponse,
    status_code=201,
    dependencies=[Depends(require_permission("template.write"))],
    summary="Scaffold a new project from a template",
)
async def generate_from_template(
    body: GenerateFromTemplateRequest, manager: WorkspaceManagerDep
) -> GenerateFromTemplateResponse:
    from ducta.console.core import ConfigFormat
    from ducta.console.template import TemplateGenerator, TemplateType

    with http_error_on(422):
        validate_project_name(body.project_name)

    try:
        template_type = TemplateType(body.template)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown template '{body.template}'")

    try:
        config_format = ConfigFormat(body.config_format)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown config format '{body.config_format}'")

    target = manager.root / "projects" / body.project_name
    if target.exists() and any(target.iterdir()):
        raise HTTPException(
            status_code=409, detail=f"Project '{body.project_name}' already exists and is not empty"
        )

    try:
        generator = TemplateGenerator(target, config_format)
        generator.generate_project(
            template_type,
            body.project_name,
            create_sample_code=body.include_sample_code,
            developer_sandboxes=body.sandbox_developers or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Template generation failed: {exc}")

    return GenerateFromTemplateResponse(
        project_id=body.project_name, template=body.template, path=str(target)
    )
