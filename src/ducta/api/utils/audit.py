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

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

_WRITE_LOCK = threading.Lock()


def write_audit_entry(
    *,
    user_id: str,
    username: str,
    method: str,
    path: str,
    status_code: int,
    request_id: Optional[str] = None,
    audit_log_path: Optional[Path] = None,
    username_attempted: Optional[str] = None,
) -> None:
    """Append a single JSON audit entry to audit_log_path."""
    if audit_log_path is None:
        audit_log_path = _default_audit_log_path()

    entry = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "user_id": user_id,
        "username": username,
        "action": f"{method} {path}",
        "method": method,
        "path": path,
        "status_code": status_code,
        "request_id": request_id,
    }
    if username_attempted is not None:
        # Set for a failed /auth/login (no authenticated user to attribute
        # the attempt to) — the attempted username, never the password.
        entry["username_attempted"] = username_attempted

    try:
        audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK:
            with audit_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        # Non-fatal — we never crash the request because audit write failed,
        # but we log so operators can detect audit failures.
        logger.warning("Audit log write failed: {err}", err=exc)


def _default_audit_log_path() -> Path:
    return Path.cwd().resolve() / ".ducta" / "audit.log"
