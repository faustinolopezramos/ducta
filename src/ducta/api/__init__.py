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

from ducta import __version__

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
from ducta.api.auth import AuthService, UserStore, get_user_store

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
from ducta.api.config import Settings, get_settings

# ---------------------------------------------------------------------------
# Core background services
# ---------------------------------------------------------------------------
from ducta.api.core import ConfigFileWatcher, ConfigLockManager, GitSyncManager

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
from ducta.api.db import get_db_session, get_engine, is_db_enabled

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
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
    RepositoryAdapterError,
    SyntaxValidationError,
    ValidationError,
    WorkspaceNotFoundError,
)

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
from ducta.api.execution import ExecutionManager

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
from ducta.api.main import create_app, warn_if_insecure_exposure

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
from ducta.api.middleware import RateLimitMiddleware, register_middleware

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
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
    PushPullRequest,
    PushPullResponse,
    RepositoryConnectRequest,
    RepositoryInfo,
    StructureInfo,
    TokenResponse,
    User,
)

# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------
from ducta.api.repositories import (
    ConfigRepository,
    NodeRepository,
    PipelineRepository,
    ProjectRepository,
)
from ducta.api.repository import (
    AWSAdapter,
    AzureAdapter,
    GitHubAdapter,
    LocalAdapter,
    RepositoryAdapter,
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
from ducta.api.routes import register_routes

# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
from ducta.api.services import (
    CachedConfigService,
    ConfigService,
    NodeSchemaService,
    NodeService,
    ProjectService,
    get_cached_config_service,
)

# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------
from ducta.api.source import ResolvedSource, SourceInfo, SourceResolver

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
from ducta.api.workspace import WorkspaceManager

__all__ = [
    "__version__",
    "Settings",
    "get_settings",
    "AuthenticationError",
    "ConfigFileNotFoundError",
    "ConfigValidationError",
    "ConflictError",
    "ConcurrencyError",
    "ExecutionError",
    "ExecutionNotFoundError",
    "ExpiredTokenError",
    "InvalidTokenError",
    "NodeNotFoundError",
    "NotFoundError",
    "PipelineNotFoundError",
    "ProjectAlreadyExistsError",
    "ProjectNotFoundError",
    "RepositoryAdapterError",
    "SyntaxValidationError",
    "DuctaAPIError",
    "ValidationError",
    "WorkspaceNotFoundError",
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
    "create_app",
    "warn_if_insecure_exposure",
    "AuthService",
    "UserStore",
    "get_user_store",
    "ConfigFileWatcher",
    "ConfigLockManager",
    "GitSyncManager",
    "get_db_session",
    "get_engine",
    "is_db_enabled",
    "ExecutionManager",
    "get_execution_manager",
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
    "PushPullRequest",
    "PushPullResponse",
    "RepositoryConnectRequest",
    "RepositoryInfo",
    "StructureInfo",
    "TokenResponse",
    "User",
    "ConfigRepository",
    "NodeRepository",
    "PipelineRepository",
    "ProjectRepository",
    "AWSAdapter",
    "AzureAdapter",
    "GitHubAdapter",
    "LocalAdapter",
    "RepositoryAdapter",
    "register_routes",
    "CachedConfigService",
    "ConfigService",
    "NodeSchemaService",
    "NodeService",
    "ProjectService",
    "get_cached_config_service",
    "ResolvedSource",
    "SourceInfo",
    "SourceResolver",
    "WorkspaceManager",
]
