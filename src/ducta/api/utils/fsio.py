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
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write(path: Path, data: bytes) -> None:
    """Write *data* to *path* via a temp file + atomic replace.

    The temp file lives in the same directory as *path* (so the final
    ``os.replace`` is atomic on the same filesystem) and is cleaned up if
    the write fails, so a crash never leaves readers with partial content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp", prefix=f".{path.name}.")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    """Serialize *data* as JSON and write it to *path* atomically."""
    payload = json.dumps(data, indent=indent, ensure_ascii=False, default=str)
    atomic_write(path, payload.encode("utf-8"))
