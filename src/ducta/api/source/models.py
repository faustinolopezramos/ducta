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
from typing import List, Optional

from pydantic import BaseModel, Field


class ResolvedSource(BaseModel):
    """Result of resolving a source path or Git URL to a local directory."""

    path: Path = Field(description="Absolute local path to the resolved source directory")
    source_type: str = Field(description="'local' or 'git'")
    original_source: str = Field(description="The original path or URL provided by the user")
    has_git: bool = Field(default=False, description="Whether the directory has a .git folder")
    has_project: bool = Field(
        default=False, description="Whether this is a Ducta project (ducta.yaml)"
    )
    pull_failed: bool = Field(
        default=False,
        description="If source_type='git', whether the latest git pull failed (using cached clone)",
    )

    model_config = {"arbitrary_types_allowed": True}


class SourceInfo(BaseModel):
    """Metadata about a resolved source directory."""

    name: str = Field(description="Directory name")
    path: str = Field(description="Absolute path")
    source_type: str = Field(description="'local' or 'git'")
    has_git: bool = Field(default=False)
    git_remote: Optional[str] = Field(default=None)
    has_project: bool = Field(default=False)
    environments: List[str] = Field(default_factory=list)
    config_files: List[str] = Field(default_factory=list)
    projects: List[str] = Field(
        default_factory=list,
        description="Project IDs detected under projects/*/config/project_settings.yaml",
    )
