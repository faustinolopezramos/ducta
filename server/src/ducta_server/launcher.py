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

Starting the web server: ``ducta-server`` and, when this package is installed,
``ducta ui`` / ``ducta server start``. It serves the API and the built web app.
"""

from __future__ import annotations

import os
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from loguru import logger

from ducta import state
from ducta.console.core import ExitCode
from ducta.setting.workspace import detect_workspace

_DEFAULT_DB_PATH = state.user_dir("executions.db")


def refuse_open_bind(host: str, allow_unauthenticated: bool) -> Optional[str]:
    """Why the server must not start on ``host`` with authentication off, else None."""
    try:
        from ducta_server.config import LOCAL_HOSTS, get_settings

        get_settings.cache_clear()  # HOST was just set; a cached Settings still has the old one
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001 — an unreadable configuration fails on its own at startup
        logger.debug("Could not read the API settings to check the bind address: {}", exc)
        return None
    if settings.auth_enabled or host in LOCAL_HOSTS:
        return None
    if allow_unauthenticated:
        logger.warning(
            "SECURITY: serving on {} WITHOUT authentication (--allow-unauthenticated). Anyone "
            "who can reach this address can run pipelines and read the project.",
            host,
        )
        return None
    return (
        f"Refusing to serve on {host} without authentication: anyone who can reach it could "
        "run pipelines on this machine. Set AUTH_ENABLED=true and a strong JWT_SECRET_KEY, "
        "bind to 127.0.0.1, or pass --allow-unauthenticated if the exposure is intended."
    )


def launch_ui(
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    source: Optional[str] = None,
    db_path: Optional[str] = None,
    allow_unauthenticated: bool = False,
):
    """
    Launch the FastAPI backend which serves the React frontend.

    The server can run pipelines, so reaching it is reaching code execution: on an address
    other than this machine's it is refused unless authentication is on (``AUTH_ENABLED``),
    or ``allow_unauthenticated`` says the exposure is intended.
    """
    import urllib.parse

    import uvicorn

    # Auto-detect workspace if not provided — allows `ducta ui` from within a pipelines folder
    if not source:
        detected = detect_workspace()
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

    # The API reads where it is bound from HOST (its exposure warning does too): the
    # address given here has to be the one it sees.
    os.environ["HOST"] = host
    refusal = refuse_open_bind(host, allow_unauthenticated)
    if refusal:
        logger.error(refusal)
        return ExitCode.SECURITY_ERROR.value

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
        from ducta_server.config import get_settings

        get_settings.cache_clear()  # DATABASE_URL, HOST… are set now: read them afresh
        uvicorn.run("ducta_server.main:app", host=host, port=port, log_level="info")
        return 0
    except Exception as e:
        logger.error("Failed to start UI server: {}", e)
        return 1
