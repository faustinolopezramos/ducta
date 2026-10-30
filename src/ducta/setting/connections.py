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

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger

from ducta.gate.gateway.connector import JDBCConnector, check_jdbc_database, check_jdbc_host
from ducta.gate.gateway.manager import ConnectionManager
from ducta.setting.project.files import load_yaml

# Sourced from JDBCConnector.DRIVERS so this module never drifts out of sync
# with the driver registry (e.g. a type added via JDBCConnector.register_driver()).
SUPPORTED_TYPES = list(JDBCConnector.DRIVERS.keys())

DEFAULT_PORTS: Dict[str, int] = {
    name: cfg["default_port"] for name, cfg in JDBCConnector.DRIVERS.items()
}

_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+\Z")


def _has_control_chars(value: Any) -> bool:
    """True if ``value`` holds a line break, NUL or any other control character.

    The credentials are written to a ``.env`` one ``KEY=value`` per line, so a line break in a
    value would start a new line the loader and the API server then read as settings.
    """
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in str(value))


class IngestionServiceError(ValueError):
    """Raised when a connection request is invalid or an operation fails."""


def validate_connection_name(name: Any) -> None:
    """Raise unless ``name`` can be a connection name (it also names its ``.env`` variables)."""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise IngestionServiceError(
            "Connection name must be a non-empty identifier (letters, digits, underscore)."
        )


@dataclass
class ConnectionSpec:
    """Parameters required to create/test a database connection."""

    name: str
    source_type: str
    host: str
    port: int
    database: str
    username: str
    password: str
    description: Optional[str] = None

    def validate(self) -> None:
        validate_connection_name(self.name)
        if self.source_type not in SUPPORTED_TYPES:
            raise IngestionServiceError(
                f"Unsupported database type '{self.source_type}'. Supported: {SUPPORTED_TYPES}"
            )
        for field_name in ("host", "database", "username", "password"):
            if not getattr(self, field_name):
                raise IngestionServiceError(f"'{field_name}' is required")
        try:
            check_jdbc_host(self.host)
            check_jdbc_database(self.database)
        except ValueError as error:
            raise IngestionServiceError(str(error)) from error
        for field_name in ("username", "password"):
            if _has_control_chars(getattr(self, field_name)):
                raise IngestionServiceError(
                    f"'{field_name}' cannot contain line breaks or other control characters"
                )
        if not isinstance(self.port, int) or self.port <= 0 or self.port > 65535:
            raise IngestionServiceError(f"Invalid port: {self.port}")


def _sources_path(workspace: Path) -> str:
    """Where the project keeps its connections — the engine's answer: a format-2
    project's ``settings.ingestion.sources_path``, else ``config/sources.yaml``."""
    from ducta.setting.project import files as pf

    # ducta.yaml, .toml or .json: reading only the YAML one sent a TOML or JSON
    # project's connections to config/sources.yaml, where its runs never look.
    for project_file in pf.find_files(workspace, "ducta")[:1]:
        try:
            doc = pf.load(project_file) or {}
            path = ((doc.get("settings") or {}).get("ingestion") or {}).get("sources_path")
            if isinstance(path, str) and path.strip():
                return path
        except (OSError, ValueError, AttributeError):
            pass
    return "config/sources.yaml"


class IngestionService:
    """Manage declarative JDBC connections (``config/sources.yaml`` + ``.env``)."""

    def __init__(self, workspace: Path | str = "."):
        self.workspace = Path(workspace)
        self._sources_setting = _sources_path(self.workspace)
        self.config_path = self.workspace / self._sources_setting
        self.env_path = self.workspace / ".env"
        self.gitignore_path = self.workspace / ".gitignore"

    # ── Read ────────────────────────────────────────────────────────────────

    def list_connections(self) -> List[Dict[str, Any]]:
        """Return metadata for every configured connection (never credentials).

        Reads ``sources.yaml`` directly — no ``ConnectionManager`` — so listing
        never triggers JDBC driver downloads or requires network access.
        """
        sources = self._load_sources()["sources"]
        return [self._source_info(name, cfg) for name, cfg in sources.items()]

    def get_connection(self, name: str) -> Dict[str, Any]:
        """Return metadata for a single connection (never credentials)."""
        sources = self._load_sources()["sources"]
        if name not in sources:
            raise IngestionServiceError(f"Connection '{name}' not found")
        return self._source_info(name, sources[name])

    @staticmethod
    def _source_info(name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": name,
            "type": cfg.get("type"),
            "host": cfg.get("host"),
            "port": cfg.get("port"),
            "database": cfg.get("database"),
            "description": cfg.get("description", ""),
        }

    # ── Test ────────────────────────────────────────────────────────────────

    def test_spec(self, spec: ConnectionSpec) -> Optional[bool]:
        """Test connectivity for an unsaved spec: True verified, False failed, None untested."""
        spec.validate()
        connector = JDBCConnector(
            source_type=spec.source_type,
            host=spec.host,
            port=spec.port,
            database=spec.database,
            username=spec.username,
            password=spec.password,
        )
        return connector.test_connection()

    def test_connection(self, name: str) -> Optional[bool]:
        """Test connectivity for a saved connection: True verified, False failed, None untested."""
        self._guard_config_path()
        if not self.config_path.exists():
            raise IngestionServiceError("No connections configured")
        # Read from the .env this service writes to, wherever sources_path points.
        manager = ConnectionManager(self.config_path, project_root=self.workspace)
        if name not in manager.list_sources():
            raise IngestionServiceError(f"Connection '{name}' not found")
        return manager.get(name).test_connection()

    # ── Write ───────────────────────────────────────────────────────────────

    def create_connection(self, spec: ConnectionSpec, overwrite: bool = False) -> Dict[str, Any]:
        """Persist a connection: write sources.yaml + .env, ensure .gitignore.

        Returns the created connection metadata (no credentials).
        """
        spec.validate()
        config = self._load_sources()
        if spec.name in config["sources"] and not overwrite:
            raise IngestionServiceError(
                f"Connection '{spec.name}' already exists (use overwrite to replace)"
            )
        # Credentials live under NAME.upper(): names that differ only in case would
        # silently overwrite each other's login.
        clash = next(
            (
                other
                for other in config["sources"]
                if other != spec.name and str(other).upper() == spec.name.upper()
            ),
            None,
        )
        if clash is not None:
            raise IngestionServiceError(
                f"Connection '{spec.name}' clashes with '{clash}': both keep their credentials "
                f"under {spec.name.upper()}_USER / {spec.name.upper()}_PASSWORD. Pick a name "
                "that differs by more than case."
            )

        entry: Dict[str, Any] = {
            "type": spec.source_type,
            "host": spec.host,
            "port": spec.port,
            "database": spec.database,
        }
        if spec.description:
            entry["description"] = spec.description
        config["sources"][spec.name] = entry

        self._save_sources(config)
        self._write_credentials(spec.name, spec.username, spec.password)
        self._ensure_gitignore()

        logger.info("Ingestion connection '{}' saved to {}", spec.name, self.config_path)
        return self.get_connection(spec.name)

    def delete_connection(self, name: str) -> None:
        """Remove a connection from sources.yaml, and its login from the project's .env."""
        config = self._load_sources()
        sources = config["sources"]
        if name not in sources:
            raise IngestionServiceError(f"Connection '{name}' not found")
        del sources[name]
        self._save_sources(config)
        # A password nobody uses any more should not stay on disk. (Another source whose
        # name differs only in case would share these variables: then they stay.)
        if not any(str(other).upper() == name.upper() for other in sources):
            self._drop_credentials(name)
        logger.info("Ingestion connection '{}' removed from {}", name, self.config_path)

    # ── Internals ───────────────────────────────────────────────────────────

    def _guard_config_path(self) -> None:
        """``sources_path`` comes from the project file: it must stay inside the project."""
        root = self.workspace.resolve()
        target = self.config_path.resolve()
        if target != root and root not in target.parents:
            raise IngestionServiceError(
                f"settings.ingestion.sources_path '{self._sources_setting}' points outside "
                "the project; use a path inside it"
            )

    def _load_sources(self) -> Dict[str, Any]:
        """The sources file as a mapping whose ``sources`` is always a mapping."""
        self._guard_config_path()
        config: Any = {}
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = load_yaml(f) or {}
        if not isinstance(config, dict):
            raise IngestionServiceError(
                f"{self.config_path} must be a mapping with a 'sources' key"
            )
        if config.get("sources") is None:  # absent, or written `sources:` with nothing under it
            config["sources"] = {}
        if not isinstance(config["sources"], dict):
            raise IngestionServiceError(f"'sources' in {self.config_path} must be a mapping")
        return config

    def _save_sources(self, config: Dict[str, Any]) -> None:
        self._guard_config_path()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    def _write_credentials(self, connection_name: str, username: str, password: str) -> None:
        # Keyed per-connection (not per source_type): two connections of the
        # same database engine (e.g. two Postgres sources) must not share
        # one .env entry and silently overwrite each other's credentials.
        # connection_name is already validated against _NAME_RE by
        # ConnectionSpec.validate(), so it's safe to use as an env key.
        for label, value in (("username", username), ("password", password)):
            if _has_control_chars(value):
                raise IngestionServiceError(
                    f"'{label}' cannot contain line breaks or other control characters"
                )
        prefix = connection_name.upper()
        keep = self._env_lines_without(prefix)
        # Single-quoted, so the value comes back exactly: read_dotenv strips surrounding
        # whitespace and one pair of outer quotes, which would eat a password's own.
        keep.append(f"{prefix}_USER='{username}'")
        keep.append(f"{prefix}_PASSWORD='{password}'")
        self._write_env(keep)

    def _env_lines_without(self, prefix: str) -> list:
        """The .env lines left once ``<prefix>_USER`` and ``<prefix>_PASSWORD`` are dropped."""
        lines = self.env_path.read_text().splitlines() if self.env_path.exists() else []
        own = re.compile(rf"^\s*(?:export\s+)?{re.escape(prefix)}_(?:USER|PASSWORD)\s*=")
        return [ln for ln in lines if not own.match(ln)]

    def _drop_credentials(self, connection_name: str) -> None:
        if not self.env_path.exists():
            return
        before = self.env_path.read_text().splitlines()
        after = self._env_lines_without(connection_name.upper())
        if after != before:
            self._write_env(after)

    def _write_env(self, lines: list) -> None:
        """Replace .env with ``lines``: owner-only from the first byte, all or nothing.

        Written to a sibling file that is never readable by anyone else and then renamed
        over .env, so a crash cannot leave a truncated file (every other secret in it lost)
        and an old, more open mode never exposes the new contents.
        """
        tmp = self.env_path.with_name(f".{self.env_path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write("\n".join(lines) + "\n" if lines else "")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.env_path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    #: What a project must never commit: the credentials file.
    _GITIGNORE_ENTRIES = (".env",)

    def _ensure_gitignore(self) -> None:
        content = self.gitignore_path.read_text() if self.gitignore_path.exists() else ""
        present = set(content.split())
        missing = [entry for entry in self._GITIGNORE_ENTRIES if entry not in present]
        if missing:
            prefix = (content.rstrip("\n") + "\n") if content else ""
            self.gitignore_path.write_text(prefix + "\n".join(missing) + "\n")

    @staticmethod
    def default_port(source_type: str) -> int:
        return DEFAULT_PORTS.get(source_type, 0)
