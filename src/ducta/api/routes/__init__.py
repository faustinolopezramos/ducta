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

from fastapi import FastAPI  # type: ignore

from ducta.api.routes.auth import router as auth_router
from ducta.api.routes.certificates import router as certificates_router
from ducta.api.routes.certificates_standalone import router as certificates_standalone_router
from ducta.api.routes.configs import router as configs_router
from ducta.api.routes.environments import router as environments_router
from ducta.api.routes.execution import router as execution_router
from ducta.api.routes.execution import ws_router as execution_ws_router
from ducta.api.routes.git import router as git_router
from ducta.api.routes.health import router as health_router
from ducta.api.routes.ingestion import router as ingestion_router
from ducta.api.routes.mlops import router as mlops_router
from ducta.api.routes.nodes import router as nodes_router
from ducta.api.routes.projects import router as projects_router
from ducta.api.routes.quality import router as quality_router
from ducta.api.routes.schedules import router as schedules_router
from ducta.api.routes.templates import router as templates_router
from ducta.api.routes.workspace import router as workspace_router
from ducta.api.routes.workspace_files import router as workspace_files_router

API_PREFIX = "/api"


def register_routes(app: FastAPI) -> None:
    """Attach all API routers to the FastAPI application.

    Domain hierarchy enforced:
      Workspace → Project → Pipeline → Node

    Route groups:
      - Health / Auth (no workspace context)
      - Workspace (source resolution)
      - Project + Pipeline (nested under project)
      - Node (workspace-scoped definitions)
      - Execution (run management + WebSocket logs)
      - Config / Environment (workspace config files)
      - Git (version control operations)
    """
    # Health probes — no prefix, must be reachable without auth
    app.include_router(health_router)

    # Auth — no workspace dependency
    app.include_router(auth_router, prefix=API_PREFIX)

    # Workspace — metadata and source resolution
    app.include_router(workspace_router, prefix=API_PREFIX)

    # Domain hierarchy: Project → Pipeline → Node
    app.include_router(projects_router, prefix=API_PREFIX)
    app.include_router(nodes_router, prefix=API_PREFIX)

    # Supporting domain: configs and environments
    app.include_router(configs_router, prefix=API_PREFIX)
    app.include_router(environments_router, prefix=API_PREFIX)

    # Execution engine (HTTP + WebSocket) + Run Certificates + Schedules
    app.include_router(execution_router, prefix=API_PREFIX)
    app.include_router(execution_ws_router, prefix=API_PREFIX)
    app.include_router(certificates_router, prefix=API_PREFIX)
    # Standalone certificate verification: no project/workspace scope and
    # deliberately no `Depends(require_permission(...))` — this is meant to be
    # usable by someone with no account on this instance who was handed a
    # certificate directly (see certificates_standalone.py's own docstring).
    app.include_router(certificates_standalone_router, prefix=API_PREFIX)
    app.include_router(schedules_router, prefix=API_PREFIX)

    # Version control
    app.include_router(git_router, prefix=API_PREFIX)

    # MLOps — experiment tracking and model registry
    app.include_router(mlops_router, prefix=API_PREFIX)

    # Data quality — run and inspect checks
    app.include_router(quality_router, prefix=API_PREFIX)

    # Ingestion — database connection management
    app.include_router(ingestion_router, prefix=API_PREFIX)

    # Project scaffolding from templates
    app.include_router(templates_router, prefix=API_PREFIX)

    # File browser
    app.include_router(workspace_files_router, prefix=API_PREFIX)
