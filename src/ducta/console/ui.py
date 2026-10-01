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

import os
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from loguru import logger

_DEFAULT_DB_PATH = Path.home() / ".ducta" / "executions.db"


def _detect_ducta_workspace() -> Optional[str]:
    """Detect if the current directory (or any parent) is a Ducta workspace."""
    from ducta.api.workspace.utils import normalize_workspace_path

    _ENV_NAMES = (
        "ducta.yaml",
        "ducta.yml",
    )

    def _is_project_dir(path: Path) -> bool:
        if any((path / name).exists() for name in _ENV_NAMES):
            return True
        return (path / "config").is_dir()

    cwd = Path.cwd()

    # Walk up the directory tree looking for an environment file
    candidate = cwd
    for _ in range(5):  # limit traversal depth
        for name in _ENV_NAMES:
            if (candidate / name).exists():
                return str(normalize_workspace_path(candidate))
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent

    # Fallback: config/ directory with recognised config files in CWD
    config_dir = cwd / "config"
    if config_dir.is_dir():
        config_files = (
            list(config_dir.glob("*.yaml"))
            + list(config_dir.glob("*.yml"))
            + list(config_dir.glob("*.json"))
            + list(config_dir.glob("*.toml"))
        )
        if config_files:
            return str(normalize_workspace_path(cwd))

    # Fallback: multi-project root with a projects/ subdirectory
    projects_dir = cwd / "projects"
    if projects_dir.is_dir():
        sub_projects = [d for d in projects_dir.iterdir() if d.is_dir() and _is_project_dir(d)]
        if len(sub_projects) == 1:
            # Single project: use it unambiguously
            return str(normalize_workspace_path(sub_projects[0]))
        if len(sub_projects) > 1:
            # Multiple projects: use the workspace root (parent directory)
            # This allows the UI to show all projects in a grid
            logger.info(
                "Detected {} Ducta projects under {}. Using workspace root to display all projects.",
                len(sub_projects),
                projects_dir,
            )
            return str(normalize_workspace_path(cwd))

    return None


def launch_ui(
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    source: Optional[str] = None,
    db_path: Optional[str] = None,
    enable_terminal: bool = False,
):
    """
    Launch the FastAPI backend which serves the React frontend.
    """
    import urllib.parse

    import uvicorn

    # Auto-detect workspace if not provided — allows `ducta ui` from within a pipelines folder
    if not source:
        detected = _detect_ducta_workspace()
        if detected:
            source = detected
            logger.info(
                "Auto-detected Ducta workspace at {}. Run pipelines or edit "
                "configuration through the UI. To use a different workspace, "
                "pass --source <path>.",
                detected,
            )

    # Share the resolved workspace with the server process via env var so the
    # API can auto-detect it for requests that omit the ?source= parameter.
    # This is set unconditionally — the terminal flag is separate and opt-in.
    if source:
        os.environ.setdefault("DUCTA_WORKSPACE", source)

    # Embedded web terminal is opt-in: it grants arbitrary shell execution to
    # authenticated users, so it stays disabled unless explicitly requested.
    if enable_terminal:
        os.environ["TERMINAL_ENABLED"] = "true"
        logger.warning(
            "Embedded web terminal ENABLED — authenticated users can run shell commands."
        )

    # Enable SQLite persistence by default so execution history survives restarts.
    # Users can opt out by setting DATABASE_URL="" in their environment before
    # launching — `not os.environ.get(...)` used to treat that explicit opt-out
    # identically to "unset" (both are falsy) and silently overwrote it with the
    # default path anyway. `"DATABASE_URL" not in os.environ` respects it.
    if "DATABASE_URL" not in os.environ:
        resolved_db = Path(db_path) if db_path else _DEFAULT_DB_PATH
        resolved_db.parent.mkdir(parents=True, exist_ok=True)
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{resolved_db}"
        logger.info("Execution history persistence enabled at {}", resolved_db)

    url = f"http://{host}:{port}"
    if source:
        url += f"/?source={urllib.parse.quote(source)}"
    logger.info("Launching Ducta UI at {}", url)

    if open_browser:

        def open_tab():
            time.sleep(2)
            logger.info("Opening browser at {}", url)
            webbrowser.open(url)

        thread = threading.Thread(target=open_tab)
        thread.daemon = True
        thread.start()

    try:
        uvicorn.run("ducta.api.main:app", host=host, port=port, log_level="info")
        return 0
    except Exception as e:
        logger.error("Failed to start UI server: {}", e)
        return 1
