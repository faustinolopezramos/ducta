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

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ducta.gate.base import BaseIO
from ducta.gate.constants import is_cloud_path
from ducta.gate.exceptions import ConfigurationError
from ducta.gate.validators import VALID_NAME_PATTERN, ConfigValidator


@dataclass
class _PathComponents:
    """Path components for output configuration."""

    table_name: str
    schema: str
    sub_folder: str = ""

    def __post_init__(self):
        self.table_name = str(self.table_name or "").strip()
        self.schema = str(self.schema or "").strip()
        self.sub_folder = str(self.sub_folder or "").strip()

        if not self.table_name or not self.schema:
            raise ConfigurationError("table_name and schema cannot be empty")

        # `validate_output_key` (below, in ConfigValidator) applies this same
        # pattern when these values are *parsed* from a declarative `out_key`
        # (e.g. "schema.sub_folder.table_name") — but resolve_output_path lets
        # `dataset_config` override each field explicitly, bypassing that
        # check entirely. A `table_name`/`schema`/`sub_folder` of `"../../etc"`
        # would then escape `output_path` via `Path.joinpath`. Validate here,
        # the single point where both sources converge, so neither path can
        # skip it.
        for field_name, value in (
            ("table_name", self.table_name),
            ("schema", self.schema),
            ("sub_folder", self.sub_folder),
        ):
            if value and not VALID_NAME_PATTERN.match(value):
                raise ConfigurationError(
                    f"Invalid characters in '{field_name}': '{value}'. "
                    "Use only alphanumeric, underscores, and hyphens."
                )


def join_cloud_path(*parts: str) -> str:
    """Join cloud storage paths properly."""
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    if not cleaned:
        return ""

    head = cleaned[0]
    if "://" in head:
        scheme, rest = head.split("://", 1)
        head = scheme + "://" + rest.rstrip("/")
    else:
        head = head.rstrip("/")

    tail = [p.strip("/") for p in cleaned[1:] if p.strip("/")]

    return head + ("/" + "/".join(tail) if tail else "")


def _newest_mtime(path: Path) -> Optional[float]:
    """Return the newest mtime (epoch seconds) under *path*, or None if absent."""
    if not path.exists():
        return None
    if path.is_file():
        return path.stat().st_mtime
    mtimes = [f.stat().st_mtime for f in path.rglob("*") if f.is_file()]
    return max(mtimes) if mtimes else path.stat().st_mtime


class _PathManager(BaseIO):
    """Manages path resolution and validation."""

    def __init__(self, context: Any, config_validator: ConfigValidator):
        super().__init__(context)
        self.config_validator = config_validator

    def resolve_output_path(
        self, dataset_config: Dict[str, Any], out_key: str, env: Optional[str] = None
    ) -> str:
        """Resolve complete output path."""
        parsed_key = self.config_validator.validate_output_key(out_key)

        components = _PathComponents(
            table_name=dataset_config.get("table_name", parsed_key["table_name"]),
            schema=dataset_config.get("schema", parsed_key["schema"]),
            sub_folder=dataset_config.get("sub_folder", parsed_key.get("sub_folder", "")),
        )

        output_path = self._ctx_get("output_path")
        if not output_path:
            raise ConfigurationError("output_path not configured")

        base_path = str(output_path)
        execution_mode = self._get_execution_mode()
        should_include_env = execution_mode in ("local", "distributed") and env

        parts = []
        if should_include_env:
            parts.append(env)

        parts.append(components.schema)
        if components.sub_folder:
            parts.append(components.sub_folder)
        parts.append(components.table_name)

        if is_cloud_path(base_path):
            return join_cloud_path(base_path, *parts)
        return Path(base_path).joinpath(*parts).as_posix()
