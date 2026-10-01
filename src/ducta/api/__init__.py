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

from typing import TYPE_CHECKING, Any

from ducta import __version__

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
#
# Resolved lazily through PEP 562's module `__getattr__`, for the same reason
# the top-level `ducta` façade is (see `ducta/__init__.py`): these names were
# re-exported eagerly, so *any* import under `ducta.api` executed this module
# and pulled the whole package in with it — auth (and therefore PyJWT), the
# database layer, the execution engine, every route module and the FastAPI app
# factory.
#
# That made `from ducta.api.config import Settings` — a module whose only
# dependency is pydantic-settings — fail with `ModuleNotFoundError: No module
# named 'jwt'` on an install without the API extras. It also undid the
# deliberate laziness of `ducta.api.main.__getattr__`, which exists so that
# importing the module does not build the app and tear down the process's
# logging configuration.
#
# Lazy resolution keeps `import ducta.api` cheap; each name pays for what it
# touches, and raises the underlying ImportError naming the missing extra.

_PUBLIC_API: dict[str, str] = {
    # Auth
    "AuthService": "ducta.api.auth",
    "UserStore": "ducta.api.auth",
    "get_user_store": "ducta.api.auth",
    # Configuration
    "Settings": "ducta.api.config",
    "get_settings": "ducta.api.config",
    # Core background services
    "ConfigFileWatcher": "ducta.api.core",
    "ConfigLockManager": "ducta.api.core",
    "GitSyncManager": "ducta.api.core",
    # Database
    "get_db_session": "ducta.api.db",
    "get_engine": "ducta.api.db",
    "is_db_enabled": "ducta.api.db",
    # Dependencies (FastAPI providers).
    #
    # `get_execution_manager` is deliberately the one from `dependencies`, which
    # reads the singleton off `request.app.state`, NOT the same-named factory in
    # `ducta.api.execution.manager`. The eager façade imported both and silently
    # kept whichever came first — and listed the name twice in `__all__`. Naming
    # the module once here removes the ambiguity; import the factory from
    # `ducta.api.execution.manager` directly if that is the one you want.
    "WebSocketAuthError": "ducta.api.dependencies",
    "get_config_service": "ducta.api.dependencies",
    "get_current_user": "ducta.api.dependencies",
    "get_execution_manager": "ducta.api.dependencies",
    "get_git_sync_manager": "ducta.api.dependencies",
    "get_node_service": "ducta.api.dependencies",
    "get_source_path": "ducta.api.dependencies",
    "get_workspace_manager": "ducta.api.dependencies",
    "require_permission": "ducta.api.dependencies",
    "resolve_websocket_user": "ducta.api.dependencies",
    # Exceptions
    "AuthenticationError": "ducta.api.exceptions",
    "ConcurrencyError": "ducta.api.exceptions",
    "ConfigFileNotFoundError": "ducta.api.exceptions",
    "ConfigValidationError": "ducta.api.exceptions",
    "ConflictError": "ducta.api.exceptions",
    "DuctaAPIError": "ducta.api.exceptions",
    "ExecutionError": "ducta.api.exceptions",
    "ExecutionNotFoundError": "ducta.api.exceptions",
    "ExpiredTokenError": "ducta.api.exceptions",
    "InvalidTokenError": "ducta.api.exceptions",
    "NodeNotFoundError": "ducta.api.exceptions",
    "NotFoundError": "ducta.api.exceptions",
    "PipelineNotFoundError": "ducta.api.exceptions",
    "ProjectAlreadyExistsError": "ducta.api.exceptions",
    "ProjectNotFoundError": "ducta.api.exceptions",
    "SyntaxValidationError": "ducta.api.exceptions",
    "ValidationError": "ducta.api.exceptions",
    "WorkspaceNotFoundError": "ducta.api.exceptions",
    # Execution
    "ExecutionManager": "ducta.api.execution",
    # App factory
    "create_app": "ducta.api.main",
    "warn_if_insecure_exposure": "ducta.api.main",
    # Middleware
    "RateLimitMiddleware": "ducta.api.middleware",
    "register_middleware": "ducta.api.middleware",
    # Models
    "BlameLine": "ducta.api.models",
    "CommitInfo": "ducta.api.models",
    "ConfigFileResponse": "ducta.api.models",
    "ConfigValidationResponse": "ducta.api.models",
    "ConnectRequest": "ducta.api.models",
    "DiffResponse": "ducta.api.models",
    "ExecutionResponse": "ducta.api.models",
    "ExecutionStatus": "ducta.api.models",
    "GitCommitInfo": "ducta.api.models",
    "GitCommitRequest": "ducta.api.models",
    "GitCommitResponse": "ducta.api.models",
    "GitExternalChangesResponse": "ducta.api.models",
    "GitHistoryResponse": "ducta.api.models",
    "GitStageRequest": "ducta.api.models",
    "GitStageResponse": "ducta.api.models",
    "GitStatusResponse": "ducta.api.models",
    "LoginRequest": "ducta.api.models",
    "StructureInfo": "ducta.api.models",
    "TokenResponse": "ducta.api.models",
    "User": "ducta.api.models",
    # Repositories
    "ConfigRepository": "ducta.api.repositories",
    "NodeRepository": "ducta.api.repositories",
    "ProjectRepository": "ducta.api.repositories",
    # Routes
    "register_routes": "ducta.api.routes",
    # Services
    "ConfigService": "ducta.api.services",
    "NodeSchemaService": "ducta.api.services",
    "NodeService": "ducta.api.services",
    "ProjectService": "ducta.api.services",
    # Source resolution
    "ResolvedSource": "ducta.api.source",
    "SourceInfo": "ducta.api.source",
    "SourceResolver": "ducta.api.source",
    # Version control adapters
    # Workspace
    "WorkspaceManager": "ducta.api.workspace",
}

if TYPE_CHECKING:  # pragma: no cover - for type checkers and IDE completion
    from ducta.api.auth import AuthService, UserStore, get_user_store
    from ducta.api.config import Settings, get_settings
    from ducta.api.core import ConfigFileWatcher, ConfigLockManager, GitSyncManager
    from ducta.api.db import get_db_session, get_engine, is_db_enabled
    from ducta.api.dependencies import (
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
    from ducta.api.exceptions import (
        AuthenticationError,
        ConcurrencyError,
        ConfigFileNotFoundError,
        ConfigValidationError,
        ConflictError,
        DuctaAPIError,
        ExecutionError,
        ExecutionNotFoundError,
        ExpiredTokenError,
        InvalidTokenError,
        NodeNotFoundError,
        NotFoundError,
        PipelineNotFoundError,
        ProjectAlreadyExistsError,
        ProjectNotFoundError,
        SyntaxValidationError,
        ValidationError,
        WorkspaceNotFoundError,
    )
    from ducta.api.execution import ExecutionManager
    from ducta.api.main import create_app, warn_if_insecure_exposure
    from ducta.api.middleware import RateLimitMiddleware, register_middleware
    from ducta.api.models import (
        BlameLine,
        CommitInfo,
        ConfigFileResponse,
        ConfigValidationResponse,
        ConnectRequest,
        DiffResponse,
        ExecutionResponse,
        ExecutionStatus,
        GitCommitInfo,
        GitCommitRequest,
        GitCommitResponse,
        GitExternalChangesResponse,
        GitHistoryResponse,
        GitStageRequest,
        GitStageResponse,
        GitStatusResponse,
        LoginRequest,
        StructureInfo,
        TokenResponse,
        User,
    )
    from ducta.api.repositories import (
        ConfigRepository,
        NodeRepository,
        ProjectRepository,
    )
    from ducta.api.routes import register_routes
    from ducta.api.services import (
        ConfigService,
        NodeSchemaService,
        NodeService,
        ProjectService,
    )
    from ducta.api.source import ResolvedSource, SourceInfo, SourceResolver
    from ducta.api.workspace import WorkspaceManager


def __getattr__(name: str) -> Any:
    """Resolve a public name on first access (PEP 562)."""
    module_path = _PUBLIC_API.get(name)
    if module_path is None:
        raise AttributeError(f"module 'ducta.api' has no attribute {name!r}")

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
    "ConfigFileWatcher",
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
    "DuctaAPIError",
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
    "ConnectRequest",
    "DiffResponse",
    "ExecutionResponse",
    "ExecutionStatus",
    "GitCommitInfo",
    "GitCommitRequest",
    "GitCommitResponse",
    "GitExternalChangesResponse",
    "GitHistoryResponse",
    "GitStageRequest",
    "GitStageResponse",
    "GitStatusResponse",
    "LoginRequest",
    "StructureInfo",
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
