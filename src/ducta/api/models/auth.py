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

from typing import List

from pydantic import BaseModel, Field


class User(BaseModel):
    """Represents an authenticated user."""

    id: str = Field(description="Unique user identifier")
    username: str = Field(description="Username (login name)")
    email: str = Field(description="User email address")
    roles: List[str] = Field(
        default_factory=list,
        description="Assigned roles: admin | developer | viewer",
    )
    is_active: bool = Field(default=True, description="False if account is disabled")
    organization_id: str = Field(
        default="org_default", description="Multi-tenant organization context"
    )

    @property
    def permissions(self) -> List[str]:
        return _roles_to_permissions(self.roles)

    def has_permission(self, permission: str) -> bool:
        """Return True if this user has the given permission."""
        perms = self.permissions

        if "*" in perms:
            return True
        return permission in perms


class TokenResponse(BaseModel):
    """JWT token returned on successful login."""

    access_token: str = Field(description="Short-lived JWT access token")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(description="Access token lifetime in seconds")
    user: User


class LoginRequest(BaseModel):
    """Request body for POST /api/auth/login."""

    username: str = Field(description="Username")
    password: str = Field(description="Plain-text password")


# Map each role to its set of permissions.
# "admin" gets the wildcard "*" which matches any permission check.
ROLE_PERMISSIONS: dict[str, List[str]] = {
    "admin": ["*"],
    "developer": [
        "workspace.read",
        "workspace.write",
        "config.read",
        "config.write",
        "pipeline.read",
        "pipeline.write",
        "pipeline.execute",
        "node.read",
        "node.write",
        "dataset.read",
        "dataset.write",
        "git.read",
        "git.write",
        "git.revert",
        "repository.read",
        "repository.write",
        "execution.read",
        "execution.write",
        "project.read",
        "project.write",
        "quality.read",
        "quality.run",
        "ingestion.read",
        "ingestion.write",
        "template.read",
        "template.write",
    ],
    "viewer": [
        "workspace.read",
        "config.read",
        "pipeline.read",
        "node.read",
        "dataset.read",
        "git.read",
        "repository.read",
        "execution.read",
        "quality.read",
        "ingestion.read",
        "template.read",
    ],
}


def _roles_to_permissions(roles: List[str]) -> List[str]:
    seen: dict[str, None] = {}
    for role in roles:
        for perm in ROLE_PERMISSIONS.get(role, []):
            seen[perm] = None
    return list(seen)
