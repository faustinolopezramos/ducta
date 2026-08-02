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

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ducta.api.dependencies import ConfigServiceDep, require_permission
from ducta.api.exceptions import ConcurrencyError, ConfigFileNotFoundError, ConfigValidationError
from ducta.api.models.config import ConfigFileResponse, ConfigValidationResponse

router = APIRouter(prefix="/configs", tags=["Configs"])


_ENV_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _validate_env(env: str) -> None:
    """Validate environment identifier."""
    if not _ENV_NAME_RE.match(env):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid environment name '{env}'. "
                "Only alphanumeric characters, underscores and hyphens are allowed."
            ),
        )


class ConfigUpdateRequest(BaseModel):
    content: Dict[str, Any] = Field(description="Updated config content")
    expected_commit_sha: Optional[str] = Field(None, description="SHA for OCC validation")


@router.get(
    "/{env}",
    summary="List all configs for an environment",
    dependencies=[Depends(require_permission("config.read"))],
    responses={400: {"description": "Invalid environment name"}},
)
async def list_configs(
    env: str,
    config_svc: ConfigServiceDep,
) -> Dict[str, ConfigFileResponse]:
    """Return all resolved config files for an environment."""
    _validate_env(env)
    try:
        return config_svc.list_configs(env)
    except ConfigFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)


@router.get(
    "/{env}/{name}",
    summary="Get a single config file",
    dependencies=[Depends(require_permission("config.read"))],
    responses={400: {"description": "Invalid environment name"}},
)
async def get_config(
    env: str,
    name: str,
    config_svc: ConfigServiceDep,
) -> ConfigFileResponse:
    """Return content of a single config file."""
    _validate_env(env)
    try:
        return config_svc.get_config(name, env)
    except ConfigFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)


@router.put(
    "/{env}/{name}",
    summary="Update a config file",
    dependencies=[Depends(require_permission("config.write"))],
    responses={400: {"description": "Invalid environment name"}},
)
async def update_config(
    env: str,
    name: str,
    body: ConfigUpdateRequest,
    config_svc: ConfigServiceDep,
) -> ConfigFileResponse:
    """Update a config file and commit to git."""
    _validate_env(env)
    try:
        return config_svc.save_config(
            name, body.content, env, expected_commit_sha=body.expected_commit_sha
        )
    except ConfigFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message)
    except ConcurrencyError as exc:
        raise HTTPException(status_code=409, detail=exc.message)


@router.post(
    "/validate",
    summary="Validate all configs for an environment",
    dependencies=[Depends(require_permission("config.read"))],
)
async def validate_configs(
    config_svc: ConfigServiceDep,
    env: str = "base",
) -> ConfigValidationResponse:
    """Validate workspace configs against ducta schemas."""
    return config_svc.validate_configs(env)
