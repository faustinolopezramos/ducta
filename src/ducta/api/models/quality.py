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


class QualityCheckInfo(BaseModel):
    """Metadata for a single registered quality check."""

    name: str
    class_name: str
    module: str
    origin: str


class QualityDatasetRef(BaseModel):
    """A (pipeline, dataset) pair with at least one stored quality report."""

    pipeline_name: str
    dataset: str


class QualityDatasetSummary(BaseModel):
    """Overview of a dataset's stored quality reports (latest + trend)."""

    pipeline_name: str
    dataset: str
    run_count: int
    latest_run_id: Optional[str] = None
    latest_score: Optional[float] = None
    passed: Optional[bool] = None
    created_at: Optional[str] = None
    trend: List[Optional[float]] = Field(
        default_factory=list, description="Most recent scores, oldest first"
    )


class RunChecksRequest(BaseModel):
    """Run data-quality checks on a workspace file."""

    input_path: str = Field(description="Data file path relative to the workspace root")
    format: str = Field(default="parquet", description="Input format: parquet, csv, or json")
    config_path: Optional[str] = Field(
        default=None, description="Checks config file path relative to the workspace root"
    )
    checks: Optional[Dict[str, Any]] = Field(
        default=None, description="Inline checks configuration (alternative to config_path)"
    )
    fail_fast: bool = Field(default=False, description="Stop on the first failing check")


class ValidateConfigRequest(BaseModel):
    """Validate the quality config of a node without executing any checks."""

    node_name: str = Field(description="Node whose quality config to validate")
    config_path: str = Field(description="Nodes config file path relative to the workspace root")
    global_config_path: Optional[str] = Field(
        default=None, description="global_config file (relative) for profile resolution"
    )


class ValidateConfigResponse(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
