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

from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field  # type: ignore

if TYPE_CHECKING:
    from fastapi import Request


class SuccessResponse(BaseModel):
    """Generic success response wrapper."""

    success: bool = True
    data: Any = Field(..., description="Response payload")
    request_id: Optional[str] = Field(None, description="Request ID for tracing")


# ── Helper function to inject request_id from middleware state ──────────────


def success_response(data: Any, request: "Request | None" = None) -> SuccessResponse:
    """Create a SuccessResponse injecting the request_id from middleware state.

    Usage in route handlers:
        return success_response(data=payload, request=request)

    The request parameter is optional and can be obtained via FastAPI dependency injection.
    If provided, the request_id is extracted from request.state set by middleware.
    """
    rid: Optional[str] = None
    if request is not None:
        rid = getattr(getattr(request, "state", None), "request_id", None)
    return SuccessResponse(data=data, request_id=rid)
