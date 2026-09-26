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
from typing import Any, Dict, Optional

from loguru import logger

from ducta.api.workspace.loaders import load_config_file
from ducta.api.workspace.utils import CONFIG_EXTENSIONS, find_config_files, find_ducta_config

#: Config-name keys produced by ``find_config_files`` for the two registries.
_INPUT_KEY = "input"
_OUTPUT_KEY = "output"


class DatasetRepository:
    """Reads the ``input_config`` / ``output_config`` dataset registries."""

    def __init__(self, root: Path) -> None:
        self._root = root

    # ── Queries ───────────────────────────────────────────────────────────────

    def list_inputs(self) -> Dict[str, Any]:
        """Return every declared input dataset keyed by reference name."""
        return self._list_side(_INPUT_KEY)

    def list_outputs(self) -> Dict[str, Any]:
        """Return every declared output dataset keyed by reference name."""
        return self._list_side(_OUTPUT_KEY)

    def resolve(self, name: str, side: str) -> Optional[Dict[str, Any]]:
        """Return the registry entry for *name*, or ``None`` when undeclared."""
        return self.resolve_from(name, side, self.list_inputs(), self.list_outputs())

    @staticmethod
    def resolve_from(
        name: str, side: str, inputs: Dict[str, Any], outputs: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Same lookup as :meth:`resolve`, against registries the caller already loaded —
        lets a batch caller load ``inputs``/``outputs`` once and resolve many names."""
        primary = inputs if side == _INPUT_KEY else outputs
        entry = primary.get(name)
        if entry is not None:
            return entry if isinstance(entry, dict) else {"format": str(entry)}

        secondary = outputs if side == _INPUT_KEY else inputs
        entry = secondary.get(name)
        if entry is None:
            return None
        return entry if isinstance(entry, dict) else {"format": str(entry)}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _list_side(self, key: str) -> Dict[str, Any]:
        """Merge the base-environment registry with every project's own."""
        registry: Dict[str, Any] = {}

        base = self._load_base(key)
        registry.update(base)

        registry.update(self._load_project_registries(key))
        return registry

    def _load_base(self, key: str) -> Dict[str, Any]:
        try:
            paths = find_config_files(self._root, "base")
        except Exception as exc:  # noqa: BLE001 - a missing environment file is not fatal
            logger.debug("No base config files for '{key}' registry: {exc}", key=key, exc=exc)
            return {}
        path = paths.get(key)
        if path is None or not path.exists():
            return {}
        try:
            return load_config_file(path) or {}
        except Exception as exc:  # noqa: BLE001 - a malformed registry must not 500 the route
            logger.warning("Failed to load base '{key}' registry: {exc}", key=key, exc=exc)
            return {}

    def _load_project_registries(self, key: str) -> Dict[str, Any]:
        """Load ``input``/``output`` registries from every project in the workspace."""
        found: Dict[str, Any] = {}
        projects_dir = self._root / "projects"
        if not projects_dir.is_dir():
            return found

        for project_dir in sorted(projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            ducta_file = find_ducta_config(project_dir)
            if ducta_file:
                found.update(self._load_layered(project_dir, ducta_file, key))
            else:
                found.update(self._load_standard(project_dir, key))
        return found

    def _load_layered(self, project_dir: Path, ducta_file: Path, key: str) -> Dict[str, Any]:
        """Load each layer's registry from a project with a ``ducta.yaml``."""
        found: Dict[str, Any] = {}
        try:
            ducta_config = load_config_file(ducta_file) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to read ducta config for '{proj}': {exc}", proj=project_dir.name, exc=exc
            )
            return found

        for layer_name, layer_cfg in (ducta_config.get("layers") or {}).items():
            if not isinstance(layer_cfg, dict):
                continue
            rel = layer_cfg.get(key)
            if not rel:
                config_dir = layer_cfg.get("config") or layer_cfg.get("config_path")
                if not config_dir:
                    continue
                rel = str(Path(config_dir) / f"{key}.yaml")

            layer_root = project_dir / str(layer_cfg.get("path", layer_name))
            for candidate in self._candidates(layer_root / rel):
                try:
                    found.update(load_config_file(candidate) or {})
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to load '{key}' registry for '{proj}/{layer}': {exc}",
                        key=key,
                        proj=project_dir.name,
                        layer=layer_name,
                        exc=exc,
                    )
                break

            if not rel:
                continue
            for candidate in self._candidates(project_dir / rel):
                try:
                    found.update(load_config_file(candidate) or {})
                except Exception:  # noqa: BLE001 - best effort
                    pass
                break
        return found

    def _load_standard(self, project_dir: Path, key: str) -> Dict[str, Any]:
        """Load the registry for a project without a ``ducta.yaml``."""
        declared = self._declared_path(project_dir, f"{key}_config_path")
        if declared is not None:
            for candidate in self._candidates(declared):
                try:
                    return load_config_file(candidate) or {}
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Failed to load declared '{key}' registry for '{proj}': {exc}",
                        key=key,
                        proj=project_dir.name,
                        exc=exc,
                    )
                break

        for candidate in self._candidates(project_dir / "config" / f"{key}.yaml"):
            try:
                return load_config_file(candidate) or {}
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Failed to load '{key}' registry for '{proj}': {exc}",
                    key=key,
                    proj=project_dir.name,
                    exc=exc,
                )
            break
        return {}

    @staticmethod
    def _declared_path(project_dir: Path, config_key: str) -> Optional[Path]:
        """Resolve *config_key* out of the project's ``environment.*`` file."""
        for ext in CONFIG_EXTENSIONS:
            env_file = project_dir / f"environment{ext}"
            if not env_file.exists():
                continue
            try:
                env_data = load_config_file(env_file) or {}
                base_path = (project_dir / str(env_data.get("base_path", "."))).resolve()
                rel = (env_data.get("env_config", {}).get("base", {}) or {}).get(config_key)
                if rel:
                    return base_path / rel
            except Exception:  # noqa: BLE001 - a broken env file just means no declared path
                pass
            break  # stop after the first environment file regardless of outcome
        return None

    @staticmethod
    def _candidates(path: Path):
        """Yield *path*, then the same stem under each supported extension."""
        if path.exists():
            yield path
            return
        for ext in CONFIG_EXTENSIONS:
            alt = path.with_suffix(ext)
            if alt.exists():
                yield alt
                return
        return
