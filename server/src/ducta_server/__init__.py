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

Ducta's web server (the ``ducta-server`` distribution): the REST/WebSocket API
and the web app. It runs Ducta's engine (the ``ducta`` distribution), which it
depends on at the same version.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


def _version() -> str:
    """This distribution's version; the engine's when run from a source tree."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("ducta-server")
    except PackageNotFoundError:
        from ducta import __version__ as engine_version

        return engine_version


__version__ = _version()

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
#
# Resolved lazily through PEP 562's module `__getattr__`, for the same reason
# the top-level `ducta` façade is (see `ducta/__init__.py`): these names were
# re-exported eagerly, so *any* import under `ducta_server` executed this module
# and pulled the whole package in with it — auth (and therefore PyJWT), the
# database layer, the execution engine, every route module and the FastAPI app
# factory.
#
# That made `from ducta_server.config import Settings` — a module whose only
# dependency is pydantic-settings — fail with `ModuleNotFoundError: No module
# named 'jwt'` on an install without the API extras. It also undid the
# deliberate laziness of `ducta_server.main.__getattr__`, which exists so that
# importing the module does not build the app and tear down the process's
# logging configuration.
#
# Lazy resolution keeps `import ducta_server` cheap; each name pays for what it
# touches, and raises the underlying ImportError naming the missing extra.

_PUBLIC_API: dict[str, str] = {
    # Auth
    "AuthService": "ducta_server.auth",
    "UserStore": "ducta_server.auth",
    "get_user_store": "ducta_server.auth",
    # Configuration
    "Settings": "ducta_server.config",
    "get_settings": "ducta_server.config",
    # Core background services
    "ConfigLockManager": "ducta_server.core",
    "GitSyncManager": "ducta_server.core",
    # Database
    "get_db_session": "ducta_server.db",
    "get_engine": "ducta_server.db",
    "is_db_enabled": "ducta_server.db",
    # Dependencies (FastAPI providers).
    #
    # `get_execution_manager` is deliberately the one from `dependencies`, which
    # reads the singleton off `request.app.state`, NOT the same-named factory in
    # `ducta_server.execution.manager`. The eager façade imported both and silently
    # kept whichever came first — and listed the name twice in `__all__`. Naming
    # the module once here removes the ambiguity; import the factory from
    # `ducta_server.execution.manager` directly if that is the one you want.
    "WebSocketAuthError": "ducta_server.dependencies",
    "get_config_service": "ducta_server.dependencies",
    "get_current_user": "ducta_server.dependencies",
    "get_execution_manager": "ducta_server.dependencies",
    "get_git_sync_manager": "ducta_server.dependencies",
    "get_node_service": "ducta_server.dependencies",
    "get_source_path": "ducta_server.dependencies",
    "get_workspace_manager": "ducta_server.dependencies",
    "require_permission": "ducta_server.dependencies",
    "resolve_websocket_user": "ducta_server.dependencies",
    # Exceptions
    "AuthenticationError": "ducta_server.exceptions",
    "ConcurrencyError": "ducta.project_store.errors",
    "ConfigFileNotFoundError": "ducta.project_store.errors",
    "ConfigValidationError": "ducta.project_store.errors",
    "ConflictError": "ducta.project_store.errors",
    "StoreError": "ducta.project_store.errors",
    "ExecutionError": "ducta_server.exceptions",
    "ExecutionNotFoundError": "ducta_server.exceptions",
    "ExpiredTokenError": "ducta_server.exceptions",
    "InvalidTokenError": "ducta_server.exceptions",
    "NodeNotFoundError": "ducta.project_store.errors",
    "NotFoundError": "ducta.project_store.errors",
    "PipelineNotFoundError": "ducta.project_store.errors",
    "ProjectAlreadyExistsError": "ducta.project_store.errors",
    "ProjectNotFoundError": "ducta.project_store.errors",
    "SyntaxValidationError": "ducta.project_store.errors",
    "ValidationError": "ducta.project_store.errors",
    "WorkspaceNotFoundError": "ducta.project_store.errors",
    # Execution
    "ExecutionManager": "ducta_server.execution",
    # App factory
    "create_app": "ducta_server.main",
    "warn_if_insecure_exposure": "ducta_server.main",
    # Middleware
    "RateLimitMiddleware": "ducta_server.middleware",
    "register_middleware": "ducta_server.middleware",
    # Models
    "BlameLine": "ducta_server.models",
    "CommitInfo": "ducta_server.models",
    "ConfigFileResponse": "ducta_server.models",
    "ConfigValidationResponse": "ducta_server.models",
    "DiffResponse": "ducta_server.models",
    "ExecutionResponse": "ducta_server.models",
    "ExecutionStatus": "ducta_server.models",
    "GitCommitRequest": "ducta_server.models",
    "GitCommitResponse": "ducta_server.models",
    "GitStageRequest": "ducta_server.models",
    "GitStageResponse": "ducta_server.models",
    "LoginRequest": "ducta_server.models",
    "TokenResponse": "ducta_server.models",
    "User": "ducta_server.models",
    # Repositories
    "ConfigRepository": "ducta_server.repositories",
    "NodeRepository": "ducta_server.repositories",
    "ProjectRepository": "ducta_server.repositories",
    # Routes
    "register_routes": "ducta_server.routes",
    # Services
    "ConfigService": "ducta_server.services",
    "NodeSchemaService": "ducta_server.services",
    "NodeService": "ducta_server.services",
    "ProjectService": "ducta_server.services",
    # Source resolution
    "ResolvedSource": "ducta_server.source",
    "SourceInfo": "ducta_server.source",
    "SourceResolver": "ducta_server.source",
    # Version control adapters
    # Workspace
    "WorkspaceManager": "ducta_server.workspace",
}

if TYPE_CHECKING:  # pragma: no cover - for type checkers and IDE completion
    from ducta.project_store.errors import (
        ConcurrencyError,
        ConfigFileNotFoundError,
        ConfigValidationError,
        ConflictError,
        NodeNotFoundError,
        NotFoundError,
        PipelineNotFoundError,
        ProjectAlreadyExistsError,
        ProjectNotFoundError,
        StoreError,
        SyntaxValidationError,
        ValidationError,
        WorkspaceNotFoundError,
    )
    from ducta_server.auth import AuthService, UserStore, get_user_store
    from ducta_server.config import Settings, get_settings
    from ducta_server.core import ConfigLockManager, GitSyncManager
    from ducta_server.db import get_db_session, get_engine, is_db_enabled
    from ducta_server.dependencies import (
        WebSocketAuthError,
        get_config_service,
        get_current_user,
        get_execution_manager,
        get_git_sync_manager,
        get_node_service,
        get_source_path,
        get_workspace_manager,
        require_permission,
        resolve_websocket_user,
    )
    from ducta_server.exceptions import (
        AuthenticationError,
        ExecutionError,
        ExecutionNotFoundError,
        ExpiredTokenError,
        InvalidTokenError,
    )
    from ducta_server.execution import ExecutionManager
    from ducta_server.main import create_app, warn_if_insecure_exposure
    from ducta_server.middleware import RateLimitMiddleware, register_middleware
    from ducta_server.models import (
        BlameLine,
        CommitInfo,
        ConfigFileResponse,
        ConfigValidationResponse,
        DiffResponse,
        ExecutionResponse,
        ExecutionStatus,
        GitCommitRequest,
        GitCommitResponse,
        GitStageRequest,
        GitStageResponse,
        LoginRequest,
        TokenResponse,
        User,
    )
    from ducta_server.repositories import (
        ConfigRepository,
        NodeRepository,
        ProjectRepository,
    )
    from ducta_server.routes import register_routes
    from ducta_server.services import (
        ConfigService,
        NodeSchemaService,
        NodeService,
        ProjectService,
    )
    from ducta_server.source import ResolvedSource, SourceInfo, SourceResolver
    from ducta_server.workspace import WorkspaceManager


def __getattr__(name: str) -> Any:
    """Resolve a public name on first access (PEP 562)."""
    module_path = _PUBLIC_API.get(name)
    if module_path is None:
        raise AttributeError(f"module 'ducta_server' has no attribute {name!r}")

    import importlib

    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)


# Spelled out rather than derived from `_PUBLIC_API`, for the same reason the
# top-level façade does it: linters and IDEs read `__all__` statically, and a
# computed one makes every name in the TYPE_CHECKING block above look unused.
# `test_all_and_the_lazy_map_cannot_drift` keeps the two in step.


__all__ = [
    "__version__",
    "AuthService",
    "UserStore",
    "get_user_store",
    "Settings",
    "get_settings",
    "ConfigLockManager",
    "GitSyncManager",
    "get_db_session",
    "get_engine",
    "is_db_enabled",
    "WebSocketAuthError",
    "get_config_service",
    "get_current_user",
    "get_execution_manager",
    "get_git_sync_manager",
    "get_node_service",
    "get_source_path",
    "get_workspace_manager",
    "require_permission",
    "resolve_websocket_user",
    "AuthenticationError",
    "ConcurrencyError",
    "ConfigFileNotFoundError",
    "ConfigValidationError",
    "ConflictError",
    "StoreError",
    "ExecutionError",
    "ExecutionNotFoundError",
    "ExpiredTokenError",
    "InvalidTokenError",
    "NodeNotFoundError",
    "NotFoundError",
    "PipelineNotFoundError",
    "ProjectAlreadyExistsError",
    "ProjectNotFoundError",
    "SyntaxValidationError",
    "ValidationError",
    "WorkspaceNotFoundError",
    "ExecutionManager",
    "create_app",
    "warn_if_insecure_exposure",
    "RateLimitMiddleware",
    "register_middleware",
    "BlameLine",
    "CommitInfo",
    "ConfigFileResponse",
    "ConfigValidationResponse",
    "DiffResponse",
    "ExecutionResponse",
    "ExecutionStatus",
    "GitCommitRequest",
    "GitCommitResponse",
    "GitStageRequest",
    "GitStageResponse",
    "LoginRequest",
    "TokenResponse",
    "User",
    "ConfigRepository",
    "NodeRepository",
    "ProjectRepository",
    "register_routes",
    "ConfigService",
    "NodeSchemaService",
    "NodeService",
    "ProjectService",
    "ResolvedSource",
    "SourceInfo",
    "SourceResolver",
    "WorkspaceManager",
]
