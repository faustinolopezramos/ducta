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

Debug runs: a run in its own process under debugpy (see runner._run_debug_child),
listening on 127.0.0.1 for the browser's debugger (the API's DAP bridge) or an
IDE. Local only: nothing listens on another interface.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict

HOST = "127.0.0.1"
DEFAULT_PORT = 5678


def available() -> bool:
    return importlib.util.find_spec("debugpy") is not None


def free_port() -> int:
    """A port nothing listens on now, on the loopback interface."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def attach_config(project_root: Path, port: int) -> Dict[str, Any]:
    """The VS Code launch configuration that attaches to a debug run."""
    return {
        "name": "Attach to Ducta",
        "type": "debugpy",
        "request": "attach",
        "connect": {"host": HOST, "port": port},
        "pathMappings": [{"localRoot": "${workspaceFolder}", "remoteRoot": str(project_root)}],
        "justMyCode": True,
    }
