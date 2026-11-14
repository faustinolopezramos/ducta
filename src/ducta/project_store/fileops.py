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

import hashlib
from pathlib import Path


def safe_path(base: Path, untrusted: str) -> Path:
    """Resolve untrusted relative to base and guard against path traversal."""
    resolved = (base / untrusted).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        raise ValueError(
            f"Path traversal detected: '{untrusted}' resolves outside workspace '{base}'"
        )
    return resolved


def content_version(path: Path) -> str:
    """A short hash of what *path* holds now — its bytes, or for a directory every
    file's relative path and bytes. "" when it does not exist.
    """
    path = Path(path)
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    if path.is_dir():
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            digest.update(child.relative_to(path).as_posix().encode())
            digest.update(b"\0")
            digest.update(child.read_bytes())
            digest.update(b"\0")
    else:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def validate_version(root: Path, path: Path, expected: str | None) -> None:
    """Raise :exc:`~ducta.project_store.errors.ConcurrencyError` if *path* changed since the
    caller read it (its :func:`content_version` is no longer *expected*)."""
    if not expected:
        return
    current = content_version(path)
    if current != expected:
        from ducta.project_store.errors import ConcurrencyError

        raise ConcurrencyError(
            f"Concurrent modification detected on {Path(path).name}",
            detail={
                "path": Path(path).relative_to(root).as_posix(),
                "expected_sha": expected,
                "current_sha": current,
                "message": "The file changed since you opened it. Reload it, or compare first.",
            },
        )
