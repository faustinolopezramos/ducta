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

from typing import Literal, Optional

from pydantic import BaseModel, Field

REPO_TYPES = Literal["local", "github", "azure", "aws"]


class RepositoryConnectRequest(BaseModel):
    """Request body for POST /api/repository/connect."""

    type: REPO_TYPES = Field(..., description="Repository backend type.")
    branch: str = Field(default="main", description="Default branch name.")

    org: Optional[str] = Field(
        default=None,
        description="GitHub organization/user name or Azure DevOps org URL.",
    )
    repo: Optional[str] = Field(default=None, description="Repository name.")

    project: Optional[str] = Field(default=None, description="Azure DevOps project name.")

    region: Optional[str] = Field(default=None, description="AWS region (e.g. us-east-1).")
    aws_https_username: Optional[str] = Field(
        default=None,
        description=(
            "IAM HTTPS Git credential username for CodeCommit. "
            "Generated in IAM → User → Security credentials."
        ),
    )
    aws_https_password: Optional[str] = Field(
        default=None,
        description="IAM HTTPS Git credential password for CodeCommit.",
    )

    token: Optional[str] = Field(
        default=None,
        description=(
            "Auth token (GitHub PAT / Azure PAT / unused for AWS). "
            "Used only for connection validation. "
            "For persistent operations, set the corresponding env var instead."
        ),
    )


class RepositoryInfo(BaseModel):
    """Current repository connection information."""

    type: str = Field(description="Repository type: local | github | azure | aws")
    remote_url: str = Field(description="Remote HTTPS clone URL (without credentials)")
    branch: str = Field(description="Configured default branch")
    connected: bool = Field(description="Whether the remote is reachable")
    warning: Optional[str] = Field(
        default=None,
        description="Non-fatal caveat about this connection (e.g. an ephemeral token).",
    )


class PushPullRequest(BaseModel):
    """Optional request body for push/pull operations."""

    branch: str = Field(default="main", description="Branch to push/pull")


class PushPullResponse(BaseModel):
    """Response after a push or pull operation."""

    success: bool
    branch: str
    message: str
