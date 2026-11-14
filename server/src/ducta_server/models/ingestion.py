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

from typing import List, Optional

from pydantic import BaseModel, Field


class ConnectionInfo(BaseModel):
    """Connection metadata — never includes credentials."""

    name: str
    type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    description: str = ""


class ConnectionListResponse(BaseModel):
    connections: List[ConnectionInfo]


class ConnectionCreateRequest(BaseModel):
    """Create (or overwrite) a database connection.

    The password is written to the workspace ``.env`` (which is force-added to
    ``.gitignore``) and never returned by any read endpoint.
    """

    name: str = Field(description="Connection identifier (letters, digits, underscore)")
    type: str = Field(
        description="Database type: sqlserver, postgresql, mysql, mariadb, oracle, snowflake"
    )
    host: str = Field(description="Database host")
    port: int = Field(description="Database port")
    database: str = Field(description="Database name")
    username: str = Field(description="Database username")
    password: str = Field(description="Database password (stored in .env, never returned)")
    description: Optional[str] = Field(default=None, description="Optional description")
    overwrite: bool = Field(
        default=False, description="Replace an existing connection of the same name"
    )


class ConnectionTestRequest(BaseModel):
    """Test a connection without persisting it."""

    type: str
    host: str
    port: int
    database: str
    username: str
    password: str


class ConnectionTestResponse(BaseModel):
    ok: bool = Field(description="True if the connection was verified")
    message: str


class ConnectionUsageItem(BaseModel):
    """A recent pipeline execution that (heuristically) uses this connection."""

    execution_id: str
    pipeline_name: str
    project_id: Optional[str] = None
    status: str
    started_at: Optional[str] = None


class ConnectionUsageResponse(BaseModel):
    pipelines: List[str] = Field(
        description="Pipelines whose node source references this connection name"
    )
    executions: List[ConnectionUsageItem] = Field(
        description="Most recent executions of those pipelines"
    )
