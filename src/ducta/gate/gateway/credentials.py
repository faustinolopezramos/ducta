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

A connection's username and password: from the environment, else from the project's ``.env``.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from loguru import logger


@dataclass(frozen=True)
class Credentials:
    """A source's username and password, and where they were found."""

    #: Out of ``repr`` so a log line, a traceback or a debugger never prints them.
    username: Optional[str] = field(repr=False)
    password: Optional[str] = field(repr=False)
    #: The variable prefix they came from: ``<SOURCE>``.
    prefix: str
    #: ``environment``, ``.env`` or ``None`` when they are not set.
    where: Optional[str]


def project_root_for(start: Path) -> Path:
    """The Ducta project whose ``.env`` holds a sources file's credentials.

    The nearest ``ducta.yaml`` above ``start``; for a sources file kept outside any project
    (``sources_path: /shared/conf/sources.yaml``), the project the process runs in — where
    ``ducta init ingestion setup`` wrote them; else the working directory.
    """
    from ducta.setting.project.context import find_nearest_project

    start = Path(start)
    for candidate in (start if start.is_dir() else start.parent, Path.cwd()):
        try:
            found = find_nearest_project(candidate)
        except Exception:  # noqa: BLE001 — a lookup must not stop a credential from resolving
            found = None
        if found is not None:
            return found
    return Path.cwd()


def read_dotenv(path: Path) -> Dict[str, str]:
    """``KEY=value`` lines of ``path`` (``export`` prefix, outer quotes and comments handled).

    Read, never copied into ``os.environ``: the file would otherwise set variables of the
    process (``JAVA_TOOL_OPTIONS`` for the JVM) and outlive a rotated environment variable.
    """
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Could not read {}: {}", path, exc)
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def resolve_credentials(source_name: str, project_root: Path) -> Credentials:
    """The source's ``<SOURCE>_USER`` / ``<SOURCE>_PASSWORD``.

    Each variable is looked up in the process environment first and then in
    ``<project_root>/.env``.
    """
    dotenv = read_dotenv(Path(project_root) / ".env")

    def lookup(var: str) -> tuple:
        if os.environ.get(var):
            return os.environ[var], "environment"
        if dotenv.get(var):
            return dotenv[var], ".env"
        return None, None

    prefix = source_name.upper()
    username, user_where = lookup(f"{prefix}_USER")
    password, password_where = lookup(f"{prefix}_PASSWORD")
    if username and password:
        where = "environment" if "environment" in (user_where, password_where) else ".env"
        return Credentials(username, password, prefix, where)
    return Credentials(None, None, prefix, None)
