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

import ipaddress

from fastapi import (
    APIRouter,
    Request,  # type: ignore
)
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


#: Fields withheld from callers that are not on the loopback interface. They are
#: pure reconnaissance to anyone else: the exact interpreter and OS build narrow
#: down which CVEs apply, and `git_path` discloses an absolute filesystem path
#: (which commonly carries the account name and reveals the install layout).
_LOOPBACK_ONLY_PLATFORM_FIELDS = ("os_version", "python", "git_path", "git_version")


def _is_loopback_client(request: Request) -> bool:
    """True when the peer address is loopback (so: this machine)."""
    if request.client is None:
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


@router.get(
    "/health/platform",
    response_model=PlatformInfoResponse,
    summary="Platform and environment info",
)
async def platform_info(request: Request) -> PlatformInfoResponse:
    """Return platform info; full detail only for callers on this machine.

    This route is deliberately unauthenticated — the bundled UI fetches it
    before login to render its Git setup wizard, which needs the git version
    and path to tell the user what to install. That diagnostic is for the
    person running the server, so the detailed fields are served to loopback
    callers only; a remote anonymous caller gets the coarse fields.
    """
    info = get_platform_info()
    if not _is_loopback_client(request):
        for field in _LOOPBACK_ONLY_PLATFORM_FIELDS:
            info.pop(field, None)
    return PlatformInfoResponse(**info)
