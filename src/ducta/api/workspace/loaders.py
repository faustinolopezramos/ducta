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

from pathlib import Path
from typing import Any, Dict

import yaml  # type: ignore
from loguru import logger  # type: ignore

from ducta.api.exceptions import ConfigFileNotFoundError, ConfigValidationError
from ducta.api.utils.fsio import atomic_write
from ducta.api.workspace.utils import CONFIG_EXTENSIONS

# Maximum config file size (10 MB) to prevent YAML bomb / DoS attacks.
_MAX_CONFIG_FILE_SIZE = 10 * 1024 * 1024

# Maximum nesting depth for YAML structures (P-WORKSPACE-001: YAML Bomb Protection)
_MAX_YAML_DEPTH = 20

# Maximum number of unique keys allowed
_MAX_YAML_KEYS = 10_000


class DepthLimitedSafeLoader(yaml.SafeLoader):
    """YAML SafeLoader with protections against bombs and DoS attacks."""

    def __init__(self, stream: Any):
        super().__init__(stream)
        self._depth = 0
        self._key_count = 0

    def compose_mapping_node(self, anchor: str):
        """Override to track nesting depth."""
        self._depth += 1

        if self._depth > _MAX_YAML_DEPTH:
            raise yaml.YAMLError(
                f"YAML nesting too deep (max {_MAX_YAML_DEPTH}). "
                "Possible YAML bomb DoS attack detected."
            )

        try:
            return super().compose_mapping_node(anchor)
        finally:
            self._depth -= 1

    def construct_mapping(self, node: Any, deep: bool = False):
        """Override to track key count."""
        self._key_count += 1

        if self._key_count > _MAX_YAML_KEYS:
            raise yaml.YAMLError(
                f"YAML has too many keys (max {_MAX_YAML_KEYS}). Possible DoS attack detected."
            )

        return super().construct_mapping(node, deep=deep)


def load_config_file(path: Path) -> Dict[str, Any]:
    """Load a YAML, JSON, or TOML config file using ducta's ConfigLoaderFactory."""
    if not path.exists():
        raise ConfigFileNotFoundError(
            f"Config file not found: {path}",
            detail={"path": str(path)},
        )

    # Guard against excessively large files (YAML bomb / DoS)
    file_size = path.stat().st_size
    if file_size > _MAX_CONFIG_FILE_SIZE:
        raise ConfigValidationError(
            f"Config file too large ({file_size} bytes, max {_MAX_CONFIG_FILE_SIZE}): {path.name}",
            detail={"path": str(path), "size": file_size, "max": _MAX_CONFIG_FILE_SIZE},
        )

    try:
        suffix = path.suffix.lower()

        # Handle YAML with depth protection (P-WORKSPACE-001)
        if suffix in (".yaml", ".yml"):
            raw_content = path.read_text(encoding="utf-8")
            data = yaml.load(raw_content, Loader=DepthLimitedSafeLoader)
            return data if isinstance(data, dict) else {}

        # Handle JSON
        elif suffix == ".json":
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}

        # Handle TOML
        elif suffix == ".toml":
            try:
                import tomllib  # type: ignore
            except ImportError:
                try:
                    import tomli as tomllib  # Fallback package
                except ImportError:
                    raise ConfigValidationError(
                        "TOML support requires Python 3.11+ or 'tomli' package",
                        detail={"path": str(path)},
                    )
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}

        else:
            # Try with ConfigLoaderFactory as fallback. This path is reachable
            # for config files discovered from a workspace/repo (content the
            # API didn't write), so Python config files must never execute
            # here — allow_python=False turns a `.py` into the ordinary
            # "No supported loader" error instead of running it.
            from ducta.setting.loaders import ConfigLoaderFactory

            factory = ConfigLoaderFactory(allow_python=False)
            data = factory.load_config(path)
            return data if isinstance(data, dict) else {}

    except ConfigValidationError:
        raise
    except yaml.YAMLError as e:
        raise ConfigValidationError(
            f"Invalid YAML in '{path.name}': {e}",
            detail={"path": str(path), "error": str(e)},
        ) from e
    except Exception as exc:
        raise ConfigValidationError(
            f"Failed to load config file '{path.name}': {exc}",
            detail={"path": str(path), "error": str(exc)},
        ) from exc


_SUPPORTED_EXTENSIONS = CONFIG_EXTENSIONS


def write_config_file(path: Path, data: Dict[str, Any]) -> None:
    """Write *data* to *path* using the format matching the file's extension."""
    suffix = path.suffix.lower()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize to memory first so no partial writes reach disk.
        if suffix in (".yaml", ".yml") or suffix not in (".json", ".toml"):
            import io

            import yaml  # type: ignore

            buf = io.StringIO()
            yaml.safe_dump(data, buf, default_flow_style=False, allow_unicode=True, indent=2)
            raw: bytes = buf.getvalue().encode("utf-8")
        elif suffix == ".json":
            import json

            raw = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        else:  # .toml
            try:
                import tomli_w  # type: ignore
            except ImportError as exc:
                raise ConfigValidationError(
                    "Writing TOML files requires 'tomli_w'. Install with: pip install tomli_w",
                    detail={"path": str(path)},
                ) from exc
            raw = tomli_w.dumps(data).encode("utf-8")

        # Write to a temp file in the same directory, then atomically replace
        # the target so readers never observe partially-written content.
        atomic_write(path, raw)

        logger.debug("Wrote config file: {path}", path=path)
    except ConfigValidationError:
        raise
    except Exception as exc:
        raise ConfigValidationError(
            f"Failed to write config file '{path}': {exc}",
            detail={"path": str(path), "error": str(exc)},
        ) from exc
