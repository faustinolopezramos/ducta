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

``ducta ui`` / ``ducta server start``: start the web server when it is installed.

The web server and its UI are a separate package (``pip install ducta-server``);
this CLI only hands over to it, so a CLI-only install carries none of its
dependencies.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from ducta.console.core import ExitCode

#: What to install to get ``ducta ui``.
SERVER_PACKAGE = "ducta-server"
#: The module that starts it.
LAUNCHER_MODULE = "ducta_server.launcher"


def server_installed() -> bool:
    """True when the web server package can be imported."""
    import importlib.util

    try:
        return importlib.util.find_spec(LAUNCHER_MODULE) is not None
    except Exception:  # noqa: BLE001 — absent or broken: either way it cannot start
        return False


def launch_ui(**kwargs: Any) -> int:
    """Start the web server (``launch_ui`` in the server package), or say how to
    install it. Returns the process exit code."""
    if not server_installed():
        logger.error(
            "The web UI is installed separately: pip install {} "
            "(it installs Ducta's engine too, at the same version).",
            SERVER_PACKAGE,
        )
        return ExitCode.DEPENDENCY_ERROR.value
    import importlib

    launcher = importlib.import_module(LAUNCHER_MODULE)
    return int(launcher.launch_ui(**kwargs))
