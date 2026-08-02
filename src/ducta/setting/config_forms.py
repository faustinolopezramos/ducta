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

from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.setting.contexts import Context
from ducta.setting.loaders import ConfigLoaderFactory

# Config file extensions probed for each conventional stem, in precedence order.
_CONFIG_EXTS = (".toml", ".yaml", ".yml", ".json")

# Top-level keys that mark a single-file *bundle*.
_BUNDLE_KEYS = (
    "global_settings",
    "pipelines_config",
    "nodes_config",
    "input_config",
    "output_config",
)

# Filenames (without extension) probed when looking for a bundle file.
_BUNDLE_STEMS = ("ducta", "config", "bundle")

# Context kwarg -> accepted file stems for the directory convention.
_DIR_CONVENTION = {
    "global_settings": ("global_settings", "global"),
    "pipelines_config": ("pipelines",),
    "nodes_config": ("nodes",),
    "input_config": ("input",),
    "output_config": ("output",),
}

# Sections a quickstart ``pipeline.*`` file groups, mapped to the Context kwarg.
_QUICKSTART_SECTIONS = {
    "pipelines_config": "pipelines",
    "nodes_config": "nodes",
    "input_config": "input",
    "output_config": "output",
}


def _load(path: Path) -> Optional[Dict[str, Any]]:
    """Best-effort load of a config file; returns None on any failure."""
    try:
        data = ConfigLoaderFactory().load_config(str(path))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Flexible resolver could not load '{}': {}", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _find(directory: Path, *stems: str) -> Optional[Path]:
    """Return the first ``<stem><ext>`` file that exists in ``directory``."""
    for stem in stems:
        for ext in _CONFIG_EXTS:
            candidate = directory / f"{stem}{ext}"
            if candidate.is_file():
                return candidate
    return None


def _is_bundle(data: Dict[str, Any]) -> bool:
    return "env_config" not in data and all(k in data for k in _BUNDLE_KEYS)


class FlexibleConfigResolver:
    """Resolve a :class:`Context` from any non-canonical configuration form.

    All methods return ``None`` when the given source does not match one of the
    supported forms, so callers can fall through to the next strategy.
    """

    @staticmethod
    def resolve_file(path: Path, data: Optional[Dict[str, Any]], env: str) -> Optional[Context]:
        """Resolve from an explicitly discovered/selected config file.

        ``data`` may be pre-loaded (to avoid a second read); when ``None`` the
        file is loaded here. Returns ``None`` for an ``env_config`` root so the
        caller keeps using :class:`AppConfigManager`.
        """
        path = Path(path)
        if data is None:
            data = _load(path)
        if not isinstance(data, dict):
            return None
        if "env_config" in data:
            return None  # canonical root — not our concern
        if _is_bundle(data):
            return _build_bundle(data, env, path)
        # A non-bundle file (e.g. a bare global settings file): treat its
        # directory as the project root and try the directory/quickstart forms.
        return FlexibleConfigResolver.resolve_dir(path.parent, env)

    @staticmethod
    def resolve_dir(base_path: Path, env: str) -> Optional[Context]:
        """Resolve from a project directory with no ``env_config`` root."""
        base = Path(base_path)
        if not base.is_dir():
            return None

        # 1. Bundle file at the project root.
        bundle_file = _find(base, *_BUNDLE_STEMS)
        if bundle_file is not None:
            data = _load(bundle_file)
            if data is not None and _is_bundle(data):
                logger.info("Resolved config form: bundle ({})", bundle_file.name)
                return _build_bundle(data, env, bundle_file)

        # 2. Directory convention (root and/or config/ subdirectory).
        conv_paths = _dir_convention_paths(base)
        if conv_paths is not None:
            logger.info("Resolved config form: directory convention ({})", base)
            return _build_from_paths(conv_paths, env)

        # 3. Quickstart: global.* + grouped pipeline.*
        quickstart = _build_quickstart(base, env)
        if quickstart is not None:
            logger.info("Resolved config form: quickstart 2-file ({})", base)
            return quickstart

        return None


def _dir_convention_paths(root: Path) -> Optional[Dict[str, str]]:
    """Locate the five standard config files under ``root`` or ``root/config``.

    Each file may live directly in ``root`` or in a ``config/`` subdirectory,
    so a project can keep ``global.yaml`` at the root and the rest under
    ``config/`` (or all five together in either place). Returns ``None`` unless
    all five are found.
    """
    search_dirs = [root, root / "config"]
    result: Dict[str, str] = {}
    for kwarg, stems in _DIR_CONVENTION.items():
        found: Optional[Path] = None
        for directory in search_dirs:
            if directory.is_dir():
                found = _find(directory, *stems)
                if found is not None:
                    break
        if found is None:
            return None
        result[kwarg] = str(found)
    return result


def _build_quickstart(base: Path, env: str) -> Optional[Context]:
    """Build a Context from ``global.*`` + a grouped ``pipeline.*`` file."""
    global_file = _find(base, "global", "global_settings")
    grouped_file = _find(base, "pipeline")
    if global_file is None or grouped_file is None:
        return None

    grouped = _load(grouped_file)
    if grouped is None:
        return None

    kwargs: Dict[str, Any] = {"global_settings": str(global_file)}
    for kwarg, section in _QUICKSTART_SECTIONS.items():
        kwargs[kwarg] = grouped.get(section, {}) or {}

    context = Context(env=env, **kwargs)
    context._config_file_path = str(global_file.resolve())
    return context


def _build_bundle(data: Dict[str, Any], env: str, source: Path) -> Context:
    """Build a Context from a single-file bundle's inline sections."""
    context = Context(
        global_settings=data["global_settings"],
        pipelines_config=data["pipelines_config"],
        nodes_config=data["nodes_config"],
        input_config=data["input_config"],
        output_config=data["output_config"],
        env=env,
    )
    context._config_file_path = str(Path(source).resolve())
    return context


def _build_from_paths(paths: Dict[str, str], env: str) -> Context:
    """Build a Context from a mapping of the five ``*_config`` file paths."""
    context = Context(
        global_settings=paths["global_settings"],
        pipelines_config=paths["pipelines_config"],
        nodes_config=paths["nodes_config"],
        input_config=paths["input_config"],
        output_config=paths["output_config"],
        env=env,
    )
    context._config_file_path = paths["global_settings"]
    return context
