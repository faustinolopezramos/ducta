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

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class ProjectResponse(BaseModel):
    """Full representation of a project returned by the API."""

    id: str = Field(description="Project slug/identifier (directory name)")
    name: str = Field(description="Human-readable project name")
    description: Optional[str] = Field(default=None, description="Project description")
    workspace: str = Field(description="Workspace root path this project belongs to")
    pipeline_count: int = Field(default=0, description="Number of pipelines in this project")
    variables: Dict[str, Any] = Field(
        default_factory=dict,
        description="Shared variables available to all pipelines in this project",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary project metadata (team, cost_center, etc.)",
    )
    created_at: Optional[str] = Field(default=None, description="ISO-8601 creation timestamp")
    updated_at: Optional[str] = Field(default=None, description="ISO-8601 last update timestamp")

    # HATEOAS links for discoverability
    links: Dict[str, str] = Field(
        default_factory=dict,
        alias="_links",
        description="Hypermedia links",
    )

    model_config = {"populate_by_name": True}


class ProjectListResponse(BaseModel):
    """Paginated list of projects."""

    projects: List[ProjectResponse]
    count: int
    total: int = Field(default=0, description="Total number of projects")
    skip: int = Field(default=0, description="Number of records skipped")
    limit: int = Field(default=0, description="Maximum number of records returned")


class ProjectCreateRequest(BaseModel):
    """Request body to create a new project inside a workspace."""

    name: str = Field(
        description="Project identifier — used as directory name. "
        "Alphanumeric, hyphens and underscores only.",
        min_length=1,
        max_length=64,
    )
    description: Optional[str] = Field(default=None, max_length=500)
    variables: Dict[str, Any] = Field(
        default_factory=dict,
        description="Shared variables inherited by all pipelines in this project",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata (e.g. team, cost_center, owner)",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        import re

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_\-]*$", v):
            raise ValueError(
                f"Invalid project name '{v}'. "
                "Must start with a letter and contain only letters, digits, hyphens or underscores."
            )
        return v.lower()


class ProjectUpdateRequest(BaseModel):
    """Request body to update an existing project's metadata."""

    description: Optional[str] = Field(default=None, max_length=500)
    variables: Optional[Dict[str, Any]] = Field(default=None)
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class ImportProjectRequest(BaseModel):
    """Request body to import an existing directory as a project."""

    path: str = Field(
        description="Absolute filesystem path to an existing project directory. "
        "Must reside inside the workspace's projects/ folder.",
    )
    name: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Override project slug/id. Defaults to the directory name.",
    )
    description: Optional[str] = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        import re

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_\-]*$", v):
            raise ValueError(
                f"Invalid project name '{v}'. "
                "Must start with a letter and contain only letters, digits, hyphens or underscores."
            )
        return v.lower()
