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

from fastapi import APIRouter
from pydantic import BaseModel

from ducta import __version__
from ducta.api.models.git import PlatformInfoResponse
from ducta.api.utils.platform_utils import get_platform_info

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health_check() -> HealthResponse:
    """Return a 200 OK response to indicate the service is alive."""
    return HealthResponse(status="ok", version=__version__)


@router.get("/health/ready", response_model=HealthResponse, summary="Readiness probe")
async def readiness_check() -> HealthResponse:
    """Return a 200 OK response when the service is ready."""
    # In Fase 1+ this can check workspace accessibility, DB connections, etc.
    return HealthResponse(status="ready", version=__version__)


@router.get(
    "/health/platform",
    response_model=PlatformInfoResponse,
    summary="Platform and environment info",
)
async def platform_info() -> PlatformInfoResponse:
    """Return platform and environment info."""
    info = get_platform_info()
    return PlatformInfoResponse(**info)
