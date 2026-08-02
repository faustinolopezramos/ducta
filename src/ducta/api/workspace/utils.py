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
from typing import Dict

# Names of config files that ducta recognises (all five required by ContextLoader)
CONFIG_FILE_NAMES = ("global_settings", "pipelines", "nodes", "input", "output")
CONFIG_EXTENSIONS = (".yaml", ".yml", ".json", ".toml")

_INTERMEDIATE_FALLBACK: Dict[str, list] = {
    "staging": ["prod"],
}


def find_config_files(workspace_root: Path, env: str) -> Dict[str, Path]:
    """Return a mapping of config-name -> resolved Path for files belonging to *env*.

    Resolution order (highest priority last, mirrors CLI FALLBACK_CHAINS):
      base → intermediate envs (e.g. prod for staging) → target env

    Note:
        Some environments silently inherit from others via ``_INTERMEDIATE_FALLBACK``
        before the target env is applied. For example, requesting ``"staging"``
        also loads ``"prod"`` config as an intermediate layer.
    """
    from ducta.api.utils.git_utils import safe_path  # avoid circular
    from ducta.api.workspace.loaders import load_environment_yaml  # avoid circular

    env_settings = load_environment_yaml(workspace_root)
    # `base_path` and every path in `env_config` below come from this
    # workspace's own environment.yaml — content a cloned repo controls, not
    # necessarily the caller. `Path.__truediv__` silently discards
    # `workspace_root` when the declared path is absolute (standard pathlib
    # behavior), so an unconfined join/resolve here would let
    # `base_path: "/etc"` (or `..`) escape the workspace entirely.
    # `safe_path` resolves relative to workspace_root and rejects anything
    # that lands outside it.
    base_path = safe_path(workspace_root, str(env_settings.get("base_path", ".")))

    env_config: Dict[str, Dict[str, str]] = env_settings.get("env_config", {})

    # Start with base paths (always required)
    merged: Dict[str, str] = dict(env_config.get("base", {}))

    # Apply intermediate fallbacks (e.g. prod before staging)
    for intermediate in _INTERMEDIATE_FALLBACK.get(env, []):
        merged.update(env_config.get(intermediate, {}))

    # Apply target env overrides last (highest priority)
    if env != "base":
        merged.update(env_config.get(env, {}))

    result: Dict[str, Path] = {}
    for key, rel_path in merged.items():
        # Strip the "_path" suffix, then any trailing "_config" to get a clean name.
        # e.g. "pipelines_config_path" -> "pipelines_config" -> "pipelines"
        # e.g. "global_settings_path" -> "global_settings" (no _config suffix)
        name = key.removesuffix("_path").removesuffix("_config")
        resolved = safe_path(base_path, rel_path)

        # If the specified path doesn't exist, probe alternative extensions so
        # projects using .toml / .json configs work without an explicit environment
        # file that spells out the exact extension.
        if not resolved.exists():
            for ext in CONFIG_EXTENSIONS:
                alt = resolved.with_suffix(ext)
                if alt.exists():
                    resolved = alt
                    break

        result[name] = resolved

    return result


def resolve_module_path(workspace_root: Path, module_dotted: str) -> Path:
    """Convert a dotted module path to a ``.py`` file path inside the workspace."""
    from ducta.api.utils.git_utils import safe_path  # avoid circular at top level

    parts = module_dotted.split(".")
    relative = Path(*parts).with_suffix(".py")
    return safe_path(workspace_root, str(relative))


def normalize_workspace_path(path: Path) -> Path:
    """Detect if path is a project directory and return the workspace root instead."""
    path = path.resolve()
    _ENV_EXTS = (".yml", ".yaml", ".toml", ".json")

    # Rule 1: self-contained workspace (own environment file).
    if any((path / f"environment{ext}").exists() for ext in _ENV_EXTS):
        return path

    # Rule 2: self-contained workspace (own config/ directory).
    if (path / "config").is_dir():
        return path

    # Rule 3: sub-project under projects/ with no own config — use the workspace root.
    if path.parent.name == "projects":
        return path.parent.parent

    return path
