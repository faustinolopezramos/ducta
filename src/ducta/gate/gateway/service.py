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

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger

from .connector import JDBCConnector
from .manager import ConnectionManager

# Sourced from JDBCConnector.DRIVERS so this module never drifts out of sync
# with the driver registry (e.g. a type added via JDBCConnector.register_driver()).
SUPPORTED_TYPES = list(JDBCConnector.DRIVERS.keys())

DEFAULT_PORTS: Dict[str, int] = {
    name: cfg["default_port"] for name, cfg in JDBCConnector.DRIVERS.items()
}

_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")


class IngestionServiceError(ValueError):
    """Raised when a connection request is invalid or an operation fails."""


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
        if not self.name or not _NAME_RE.match(self.name):
            raise IngestionServiceError(
                "Connection name must be a non-empty identifier (letters, digits, underscore)."
            )
        if self.source_type not in SUPPORTED_TYPES:
            raise IngestionServiceError(
                f"Unsupported database type '{self.source_type}'. Supported: {SUPPORTED_TYPES}"
            )
        for field_name in ("host", "database", "username", "password"):
            if not getattr(self, field_name):
                raise IngestionServiceError(f"'{field_name}' is required")
        if not isinstance(self.port, int) or self.port <= 0 or self.port > 65535:
            raise IngestionServiceError(f"Invalid port: {self.port}")


def _sources_path(workspace: Path) -> str:
    """Where the project keeps its connections — the engine's answer: a format-2
    project's ``settings.ingestion.sources_path``, else ``config/sources.yaml``."""
    project_file = workspace / "ducta.yaml"
    if project_file.is_file():
        try:
            doc = yaml.safe_load(project_file.read_text(encoding="utf-8")) or {}
            path = ((doc.get("settings") or {}).get("ingestion") or {}).get("sources_path")
            if isinstance(path, str) and path.strip():
                return path
        except (OSError, yaml.YAMLError, AttributeError):
            pass
    return "config/sources.yaml"


class IngestionService:
    """Manage declarative JDBC connections (``config/sources.yaml`` + ``.env``)."""

    def __init__(self, workspace: Path | str = "."):
        self.workspace = Path(workspace)
        self.config_path = self.workspace / _sources_path(self.workspace)
        self.env_path = self.workspace / ".env"
        self.gitignore_path = self.workspace / ".gitignore"

    # ── Read ────────────────────────────────────────────────────────────────

    def list_connections(self) -> List[Dict[str, Any]]:
        """Return metadata for every configured connection (never credentials).

        Reads ``sources.yaml`` directly — no ``ConnectionManager`` — so listing
        never triggers JDBC driver downloads or requires network access.
        """
        sources = self._load_sources().get("sources", {})
        return [self._source_info(name, cfg) for name, cfg in sources.items()]

    def get_connection(self, name: str) -> Dict[str, Any]:
        """Return metadata for a single connection (never credentials)."""
        sources = self._load_sources().get("sources", {})
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

    def test_spec(self, spec: ConnectionSpec) -> bool:
        """Test connectivity for an unsaved spec. Returns True if verified."""
        spec.validate()
        connector = JDBCConnector(
            source_type=spec.source_type,
            host=spec.host,
            port=spec.port,
            database=spec.database,
            username=spec.username,
            password=spec.password,
        )
        return bool(connector.test_connection())

    def test_connection(self, name: str) -> bool:
        """Test connectivity for a saved connection. Returns True if verified."""
        if not self.config_path.exists():
            raise IngestionServiceError("No connections configured")
        manager = ConnectionManager(self.config_path)
        if name not in manager.list_sources():
            raise IngestionServiceError(f"Connection '{name}' not found")
        return bool(manager.get(name).test_connection())

    # ── Write ───────────────────────────────────────────────────────────────

    def create_connection(self, spec: ConnectionSpec, overwrite: bool = False) -> Dict[str, Any]:
        """Persist a connection: write sources.yaml + .env, ensure .gitignore.

        Returns the created connection metadata (no credentials).
        """
        spec.validate()
        config = self._load_sources()
        if spec.name in config.get("sources", {}) and not overwrite:
            raise IngestionServiceError(
                f"Connection '{spec.name}' already exists (use overwrite to replace)"
            )

        entry: Dict[str, Any] = {
            "type": spec.source_type,
            "host": spec.host,
            "port": spec.port,
            "database": spec.database,
        }
        if spec.description:
            entry["description"] = spec.description
        config.setdefault("sources", {})[spec.name] = entry

        self._save_sources(config)
        self._write_credentials(spec.name, spec.username, spec.password)
        self._ensure_gitignore()

        logger.info("Ingestion connection '{}' saved to {}", spec.name, self.config_path)
        return self.get_connection(spec.name)

    def delete_connection(self, name: str) -> None:
        """Remove a connection from sources.yaml (credentials in .env are kept)."""
        config = self._load_sources()
        sources = config.get("sources", {})
        if name not in sources:
            raise IngestionServiceError(f"Connection '{name}' not found")
        del sources[name]
        self._save_sources(config)
        logger.info("Ingestion connection '{}' removed from {}", name, self.config_path)

    # ── Internals ───────────────────────────────────────────────────────────

    def _load_sources(self) -> Dict[str, Any]:
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {"sources": {}}
        return {"sources": {}}

    def _save_sources(self, config: Dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    def _write_credentials(self, connection_name: str, username: str, password: str) -> None:
        # Keyed per-connection (not per source_type): two connections of the
        # same database engine (e.g. two Postgres sources) must not share
        # one .env entry and silently overwrite each other's credentials.
        # connection_name is already validated against _NAME_RE by
        # ConnectionSpec.validate(), so it's safe to use as an env key.
        prefix = connection_name.upper()
        lines = self.env_path.read_text().splitlines() if self.env_path.exists() else []
        # Drop any existing keys for this prefix so updates replace rather than duplicate.
        keep = [
            ln
            for ln in lines
            if not (ln.startswith(f"{prefix}_USER=") or ln.startswith(f"{prefix}_PASSWORD="))
        ]
        keep.append(f"{prefix}_USER={username}")
        keep.append(f"{prefix}_PASSWORD={password}")
        self.env_path.write_text("\n".join(keep) + "\n")

    def _ensure_gitignore(self) -> None:
        if self.gitignore_path.exists():
            content = self.gitignore_path.read_text()
            if ".env" not in content.split():
                self.gitignore_path.write_text(content.rstrip("\n") + "\n.env\n")
        else:
            self.gitignore_path.write_text(".env\n")

    @staticmethod
    def default_port(source_type: str) -> int:
        return DEFAULT_PORTS.get(source_type, 0)
