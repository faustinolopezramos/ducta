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

from pydantic import BaseModel, Field


class ConfigFileResponse(BaseModel):
    """Response model for a single config file."""

    name: str = Field(description="Config name (e.g. 'storage', 'compute')")
    env: str = Field(description="Environment (e.g. 'base', 'dev', 'prod')")
    path: str = Field(description="Relative path within the workspace")
    content: Dict[str, Any] = Field(description="Parsed config content")
    commit_sha: Optional[str] = Field(
        default=None, description="Git SHA of the last commit that modified this file"
    )


class ConfigValidationResponse(BaseModel):
    """Response model for config validation results."""

    valid: bool = Field(description="True if all configs passed validation")
    env: str = Field(description="Environment that was validated")
    errors: List[Dict[str, Any]] = Field(
        default_factory=list, description="List of validation errors, if any"
    )
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings")
