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

import ast
import re
from pathlib import Path
from urllib.parse import ParseResult, urlparse

from ducta.api.exceptions import SyntaxValidationError


def validate_python_syntax(code: str, source_label: str = "<string>") -> None:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        raise SyntaxValidationError(
            f"Syntax error in {source_label}: {exc.msg} (line {exc.lineno})",
            detail={
                "source": source_label,
                "msg": exc.msg,
                "lineno": exc.lineno,
                "offset": exc.offset,
                "text": exc.text,
            },
        ) from exc


def validate_identifier(name: str, field: str = "name") -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_\-\.]*$", name):
        raise ValueError(
            f"Invalid {field}: '{name}'. Must start with a letter/underscore "
            "and contain only letters, numbers, underscores, hyphens, or dots."
        )
    return name


def validate_environment_name(env: str) -> str:
    if not re.match(r"^[a-z][a-z0-9_\-]*$", env):
        raise ValueError(
            f"Invalid environment name: '{env}'. Must be lowercase and start with a letter."
        )
    return env


class URLValidationError(ValueError):
    pass


_PROHIBITED_CHARS = frozenset({"$", "`", "(", ")", ";", "&", "|", "<", ">", "\n", "\r", "\x00"})
_SSH_URL_RE = re.compile(r"^[^@:]+@[^@/:]+:[^@:]+")


def validate_git_url(url: str, allow_file: bool = False) -> ParseResult:
    if not url or not isinstance(url, str):
        raise URLValidationError("URL must be a non-empty string")

    if any(char in url for char in _PROHIBITED_CHARS):
        bad_chars = sorted(set(c for c in _PROHIBITED_CHARS if c in url))
        raise URLValidationError(f"URL contains prohibited characters: {bad_chars}")

    is_ssh_style = "@" in url and "://" not in url
    if is_ssh_style and not _SSH_URL_RE.match(url):
        raise URLValidationError(
            f"Invalid SSH URL format: {url}. Expected: git@host:path/to/repo.git"
        )

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise URLValidationError(f"Failed to parse URL: {e}")

    if is_ssh_style:
        return parsed

    allowed_schemes = (
        {"https", "http", "ssh", "git", "file"} if allow_file else {"https", "http", "ssh", "git"}
    )
    if parsed.scheme not in allowed_schemes:
        raise URLValidationError(
            f"Unsupported URL scheme '{parsed.scheme}'. Allowed: {', '.join(sorted(allowed_schemes))}"
        )

    if parsed.scheme in ("http", "https"):
        if not parsed.netloc:
            raise URLValidationError("URL missing hostname")
        if "@" in parsed.netloc:
            raise URLValidationError("HTTP/HTTPS URLs must not contain credentials in the URL.")
        hostname = parsed.hostname or ""
        if not all(c.isalnum() or c in ".-" for c in hostname):
            raise URLValidationError(f"Invalid hostname characters in: {hostname}")
    elif parsed.scheme in ("ssh", "git") and not parsed.netloc:
        raise URLValidationError(f"{parsed.scheme.upper()} URL missing host")
    elif parsed.scheme == "file" and allow_file and ".." in parsed.path:
        raise URLValidationError("File URLs must not contain '..' path traversals")

    return parsed


def validate_local_path(path: str) -> str:
    """Validate that *path* is a safe workspace-relative path."""
    if not path or not isinstance(path, str):
        raise ValueError("Path must be a non-empty string")

    if path.startswith("/") or path.startswith("\\") or path.startswith("~"):
        raise ValueError(f"Absolute paths are not allowed for workspace files: {path}")

    expanded = Path(path)
    if ".." in expanded.parts:
        raise ValueError("Path contains '..' which enables traversal attacks")
    if expanded.is_absolute():
        raise ValueError(f"Absolute paths are not allowed for workspace files: {path}")

    return str(expanded)
