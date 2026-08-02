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

from fastapi import Request, Response
from fastapi.concurrency import run_in_threadpool

from ducta.api.config import Settings

# HTTP methods that warrant an audit entry (state-changing operations)
_AUDIT_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_AUDIT_EXCLUDE_PREFIXES = ("/health",)


async def maybe_write_audit(
    request: Request,
    response: Response,
    settings: Settings,
    request_id: str,
) -> None:
    """Write an audit log entry if the request qualifies.

    Previously bailed out whenever `request.state.current_user` was unset,
    which is exactly the case for a failed login or a 401/403 from
    `get_current_user`/`require_permission` — so the audit trail only ever
    recorded requests that *succeeded*, and had no record of failed login
    attempts or rejected/forbidden requests at all.
    """
    if (
        request.method not in _AUDIT_METHODS
        or any(request.url.path.startswith(p) for p in _AUDIT_EXCLUDE_PREFIXES)
        or not settings.auth_enabled
    ):
        return

    user = getattr(request.state, "current_user", None)
    if user is None and response.status_code not in (401, 403):
        # No authenticated user and not a rejected auth attempt: nothing to
        # attribute an audit entry to (e.g. an endpoint that doesn't require
        # auth at all).
        return

    username_attempted = None
    if user is None and request.url.path.endswith("/auth/login"):
        try:
            body = await request.json()
            if isinstance(body, dict):
                username_attempted = body.get("username")
        except Exception:  # noqa: BLE001
            pass

    try:
        from ducta.api.utils.audit import write_audit_entry

        workspace_root = getattr(request.state, "source_path", None) or getattr(
            request.state, "workspace_root", None
        )
        audit_log_path = (
            (workspace_root / ".ducta" / "audit.log") if workspace_root is not None else None
        )
        # write_audit_entry does blocking file I/O under a threading.Lock —
        # keep it off the event loop.
        await run_in_threadpool(
            write_audit_entry,
            user_id=(user.id if user is not None else "anonymous"),
            username=(user.username if user is not None else "unknown"),
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            request_id=request_id,
            audit_log_path=audit_log_path,
            username_attempted=username_attempted,
        )
    except Exception:  # noqa: BLE001
        pass  # Audit failure must never break the response
