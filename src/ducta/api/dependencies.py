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
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, WebSocket  # type: ignore
from fastapi.security import OAuth2PasswordBearer  # type: ignore

from ducta.api.config import Settings, get_settings
from ducta.api.core.git_sync import GitSyncManager
from ducta.api.core.locks import ConfigLockManager
from ducta.api.exceptions import (
    AuthenticationError,
    ExpiredTokenError,
    InvalidTokenError,
    http_error_on,
)
from ducta.api.execution.manager import ExecutionManager
from ducta.api.models.auth import User
from ducta.api.services.config_service import ConfigService
from ducta.api.services.node_service import NodeService
from ducta.api.source.models import ResolvedSource
from ducta.api.source.resolver import SourceResolver
from ducta.api.workspace.manager import WorkspaceManager

SettingsDep = Annotated[Settings, Depends(get_settings)]


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login/form",
    auto_error=False,
)


def _dev_admin_user() -> User:
    """Synthetic admin user returned when authentication is disabled."""
    return User(
        id="dev-admin",
        username="dev-admin",
        email="dev@ducta.local",
        roles=["admin"],
    )


# ── Source path resolution (replaces workspace) ─────────────────────────────


def resolve_source(raw: str) -> ResolvedSource:
    """``SourceResolver.resolve`` with its failures mapped to HTTP errors:
    a bad path/URL is the caller's fault (400), a failed clone is ours (500)."""
    with http_error_on(400, ValueError), http_error_on(500, RuntimeError):
        return SourceResolver.resolve(raw)


def get_source_path(
    request: Request,
    source: Annotated[
        str | None,
        Query(description="Source path (local directory or Git URL)"),
    ] = None,
) -> Path:
    """Resolve and validate the source path provided per-request.

    Resolution order (first non-empty wins):
      1. ``?source=`` query parameter
      2. ``X-Source-Path`` request header
      3. ``DUCTA_WORKSPACE`` environment variable — set automatically by ``ducta ui``
         when it detects or receives a workspace path.

    This allows the UI to work without repeating the source on every request
    when the server was launched with ``ducta ui`` from a project directory.
    """
    import os

    resolved_source = (
        source or request.headers.get("X-Source-Path") or os.environ.get("DUCTA_WORKSPACE")
    )
    if not resolved_source:
        raise HTTPException(
            status_code=400,
            detail=(
                "Missing required 'source' query parameter or 'X-Source-Path' header. "
                "Provide a local directory path or Git repository URL "
                "via ?source= or the X-Source-Path request header."
            ),
        )

    resolved = resolve_source(resolved_source)

    request.state.source_path = resolved.path
    request.state.workspace_root = resolved.path
    return resolved.path


SourcePathDep = Annotated[Path, Depends(get_source_path)]


# Keep WorkspaceManager creation for routes that still use it (Git operations, etc.)
# It no longer validates environment.yaml — just wraps the resolved path.
def get_workspace_manager(path: SourcePathDep) -> WorkspaceManager:
    """Return a WorkspaceManager for the resolved source path."""
    return WorkspaceManager(path)


WorkspaceManagerDep = Annotated[WorkspaceManager, Depends(get_workspace_manager)]


def get_execution_manager(request: Request) -> ExecutionManager:
    """Return the application-wide singleton ExecutionManager instance."""
    return request.app.state.execution_manager


ExecutionManagerDep = Annotated[ExecutionManager, Depends(get_execution_manager)]


def get_git_sync_manager(path: SourcePathDep) -> GitSyncManager:
    """Return a GitSyncManager for the resolved source path."""
    return GitSyncManager(
        workspace_root=path,
        auto_commit=True,
        auto_commit_author="Ducta API",
        auto_commit_email="api@ducta.local",
    )


GitSyncManagerDep = Annotated[GitSyncManager, Depends(get_git_sync_manager)]


# ── Service layer dependencies ────────────────────────────────────────────────


def get_node_service(path: SourcePathDep) -> NodeService:
    return NodeService(root=path)


NodeServiceDep = Annotated[NodeService, Depends(get_node_service)]


def get_config_service(path: SourcePathDep) -> ConfigService:
    return ConfigService(root=path)


ConfigServiceDep = Annotated[ConfigService, Depends(get_config_service)]


def get_config_lock_manager(path: SourcePathDep) -> ConfigLockManager:
    """Return a ConfigLockManager for the resolved source path."""
    return ConfigLockManager(workspace_root=path)


ConfigLockManagerDep = Annotated[ConfigLockManager, Depends(get_config_lock_manager)]


async def _authenticate_token(token: str | None, settings: Settings) -> User:
    """Decode *token* and look up the corresponding user.

    Shared by the HTTP and WebSocket auth paths, which differ only in how
    they translate a failure into a transport-specific error.
    """
    if not settings.auth_enabled:
        return _dev_admin_user()

    if not token:
        raise AuthenticationError("Missing Authorization header or access_token cookie")

    from ducta.api.auth.service import get_auth_service
    from ducta.api.auth.users import get_user_store

    auth_svc = get_auth_service()
    try:
        payload = auth_svc.decode_access_token(token)
    except (ExpiredTokenError, InvalidTokenError) as exc:
        raise AuthenticationError(exc.message) from exc

    store = get_user_store()
    user = await store.get_by_id(payload["sub"])
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")

    return user


async def get_current_user(
    request: Request,
    settings: SettingsDep,
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
) -> User:
    """Validate the Bearer token and return the corresponding User."""
    if not token:
        token = request.cookies.get("access_token")

    try:
        user = await _authenticate_token(token, settings)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    request.state.current_user = user
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


class WebSocketAuthError(Exception):
    """Raised when a WebSocket token is missing or invalid."""

    def __init__(self, reason: str, code: int = 1008) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


async def resolve_websocket_user(settings: Settings, token: str | None) -> User:
    """Validate a WebSocket JWT without mutating socket state."""
    try:
        return await _authenticate_token(token, settings)
    except AuthenticationError as exc:
        raise WebSocketAuthError(f"Unauthorized: {exc.message}") from exc


def extract_ws_token(websocket: WebSocket) -> str | None:
    """Pull the bearer token out of a WebSocket handshake (header or cookie)."""
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return websocket.cookies.get("access_token")


async def authenticate_websocket(
    websocket: WebSocket,
    settings: Settings,
    *,
    permission: str | None = None,
) -> User | None:
    """Full WebSocket handshake: origin check -> rate limit -> token extract ->
    auth -> permission check.

    Closes the socket with the appropriate code/reason and returns ``None`` on
    any failure; callers must ``return`` immediately when this returns ``None``.
    Shared by every WebSocket route that needs authenticated, rate-limited,
    origin-checked connections (execution log streaming).
    """
    from ducta.api.middleware.origin import websocket_origin_allowed

    if not await websocket_origin_allowed(websocket, settings):
        return None

    if settings.rate_limit_enabled:
        from ducta.api.middleware.rate_limit import (
            get_websocket_client_key,
            get_websocket_connection_limiter,
        )

        limiter = get_websocket_connection_limiter(settings)
        if not limiter.is_allowed(get_websocket_client_key(websocket)):
            await websocket.close(code=1013, reason="Rate limit exceeded")
            return None

    token = extract_ws_token(websocket)

    try:
        user = await resolve_websocket_user(settings, token)
    except WebSocketAuthError as exc:
        await websocket.close(code=exc.code, reason=exc.reason)
        return None

    if permission and settings.auth_enabled and not user.has_permission(permission):
        await websocket.close(code=1008, reason="Forbidden: insufficient permissions")
        return None

    return user


def require_permission(permission: str):  # noqa: ANN201
    """Return a FastAPI dependency that enforces a specific permission."""

    def _check(user: CurrentUserDep):
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=403,
                detail=f"Permission '{permission}' required",
            )
        return user

    return _check
