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
from typing import Any, Dict, List

from loguru import logger

# File extensions recognised as Ducta config files.
_CONFIG_EXTENSIONS = frozenset({".yaml", ".yml", ".json", ".toml"})

# Maximum depth to scan for files (avoids scanning huge trees).
_MAX_SCAN_DEPTH = 3


class StructureDetector:
    """Analyse a directory and return its detected structure type and metadata."""

    @staticmethod
    def detect(root: Path) -> Dict[str, Any]:
        """Analyse *root* and return structure metadata."""
        root = root.resolve()

        has_env_yaml = (root / "environment.yaml").exists() or (root / "environment.yml").exists()
        has_config_dir = (root / "config").is_dir()
        has_git = (root / ".git").is_dir()

        # Collect files up to _MAX_SCAN_DEPTH
        config_files: List[str] = []
        python_files: List[str] = []
        directories: List[str] = []

        # Top-level directories
        try:
            for item in sorted(root.iterdir()):
                if item.name.startswith("."):
                    continue  # skip hidden dirs like .git, .ducta
                if item.is_dir():
                    directories.append(item.name)
        except PermissionError:
            pass

        # Scan for config and Python files
        _scan_files(root, root, config_files, python_files, depth=0)

        # Detect environments
        environments = _detect_environments(root, has_env_yaml)

        # Classify
        structure_type = _classify(
            has_env_yaml=has_env_yaml,
            has_config_dir=has_config_dir,
            config_files=config_files,
            python_files=python_files,
            directories=directories,
        )

        logger.debug(
            "StructureDetector: {root} -> {type}",
            root=root,
            type=structure_type,
        )

        return {
            "structure_type": structure_type,
            "root": str(root),
            "has_environment_yaml": has_env_yaml,
            "has_config_dir": has_config_dir,
            "has_git": has_git,
            "environments": environments,
            "config_files": config_files,
            "python_files": python_files,
            "directories": directories,
        }


# Internal helpers


# Directories always skipped during recursive scan to prevent performance issues.
_SKIP_DIRS = frozenset(
    {
        "node_modules",
        "venv",
        ".venv",
        "__pycache__",
        ".git",
        ".ducta",
        ".pytest_cache",
        ".mypy_cache",
        "dist",
        "build",
    }
)

# Maximum total files to collect (total across all scanned directories).
_MAX_TOTAL_FILES = 500

# Maximum file size (in bytes) to read for structure detection (1 MB).
_MAX_DETECT_FILE_SIZE = 1 * 1024 * 1024


def _scan_files(
    root: Path,
    current: Path,
    config_files: List[str],
    python_files: List[str],
    depth: int,
) -> None:
    """Recursively collect config and Python files up to ``_MAX_SCAN_DEPTH``."""
    if depth > _MAX_SCAN_DEPTH:
        return

    # Safety check: stop if we already have enough files to classify
    if len(config_files) + len(python_files) >= _MAX_TOTAL_FILES:
        return

    try:
        for item in sorted(current.iterdir()):
            if item.name.startswith(".") or item.name in _SKIP_DIRS:
                continue

            if item.is_file():
                rel = str(item.relative_to(root))
                if item.suffix.lower() in _CONFIG_EXTENSIONS:
                    config_files.append(rel)
                elif item.suffix.lower() == ".py":
                    python_files.append(rel)

                # Exit early if we reach the limit
                if len(config_files) + len(python_files) >= _MAX_TOTAL_FILES:
                    break
            elif item.is_dir():
                _scan_files(root, item, config_files, python_files, depth + 1)
    except PermissionError:
        pass


def _detect_environments(root: Path, has_env_yaml: bool) -> List[str]:
    """Try to extract environment names from environment.yaml or config/ layout."""
    environments: List[str] = []

    if has_env_yaml:
        # Try to parse environment.yaml for env names
        try:
            env_path = root / "environment.yaml"
            if not env_path.exists():
                env_path = root / "environment.yml"

            # Guard against oversized files (YAML bomb)
            if env_path.stat().st_size > _MAX_DETECT_FILE_SIZE:
                logger.warning("environment.yaml too large, skipping")
                return environments

            import yaml  # type: ignore[import]

            with env_path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)

            if isinstance(data, dict):
                env_config = data.get("env_config", {})
                if isinstance(env_config, dict):
                    environments = list(env_config.keys())
        except Exception:
            pass
    elif (root / "config").is_dir():
        # Infer environments from config/ sub-directories
        try:
            for item in sorted((root / "config").iterdir()):
                if item.is_dir() and not item.name.startswith("."):
                    environments.append(item.name)
        except PermissionError:
            pass

    return environments


def _classify(
    *,
    has_env_yaml: bool,
    has_config_dir: bool,
    config_files: List[str],
    python_files: List[str],
    directories: List[str],
) -> str:
    """Classify the directory structure type."""
    # Nothing at all
    if not config_files and not python_files and not directories:
        return "empty"

    # Full Ducta workspace
    if has_env_yaml and has_config_dir:
        return "ducta_workspace"

    # Has config directory with YAML files but no environment.yaml
    if has_config_dir and config_files:
        return "config_only"

    # Python files present but no Ducta config structure
    if python_files:
        return "python_project"

    # Fallback
    return "generic"
