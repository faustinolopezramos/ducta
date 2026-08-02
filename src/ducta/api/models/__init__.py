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

from ducta.api.models.auth import LoginRequest, TokenResponse, User
from ducta.api.models.config import ConfigFileResponse, ConfigValidationResponse
from ducta.api.models.execution import ExecutionResponse, ExecutionStatus
from ducta.api.models.git import BlameLine, CommitInfo, DiffResponse
from ducta.api.models.git_sync import (
    GitCommitInfo,
    GitCommitRequest,
    GitCommitResponse,
    GitExternalChangesResponse,
    GitHistoryResponse,
    GitStageRequest,
    GitStageResponse,
    GitStatusResponse,
)
from ducta.api.models.repository import (
    PushPullRequest,
    PushPullResponse,
    RepositoryConnectRequest,
    RepositoryInfo,
)
from ducta.api.models.workspace import ConnectRequest, StructureInfo

__all__ = [
    "LoginRequest",
    "TokenResponse",
    "User",
    "ConfigFileResponse",
    "ConfigValidationResponse",
    "ExecutionResponse",
    "ExecutionStatus",
    "BlameLine",
    "CommitInfo",
    "DiffResponse",
    "GitCommitInfo",
    "GitCommitRequest",
    "GitCommitResponse",
    "GitExternalChangesResponse",
    "GitHistoryResponse",
    "GitStageRequest",
    "GitStageResponse",
    "GitStatusResponse",
    "PushPullRequest",
    "PushPullResponse",
    "RepositoryConnectRequest",
    "RepositoryInfo",
    "ConnectRequest",
    "StructureInfo",
]
