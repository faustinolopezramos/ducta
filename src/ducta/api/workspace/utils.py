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
CONFIG_FILE_NAMES = ("global_config", "pipelines", "nodes", "input", "output")
CONFIG_EXTENSIONS = (".yaml", ".yml", ".json", ".toml")

#: `environment.yaml` declaration key -> the short name the rest of the API uses.
#: Keep in step with `CONFIG_FILE_NAMES` and with
#: `WorkspaceManager._CONTEXT_KEY_MAP`, which maps these names back to the
#: `*_path` keys `ContextLoader.load_from_paths` requires.
_CONFIG_KEY_TO_NAME: Dict[str, str] = {
    "global_config_path": "global_config",
    "pipelines_config_path": "pipelines",
    "nodes_config_path": "nodes",
    "input_config_path": "input",
    "output_config_path": "output",
}

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
        # Spelled out rather than derived by stripping suffixes. The old rule
        # ("strip _path, then strip _config") worked only while the first config
        # was called `global_settings_path`: that name has no `_config` suffix,
        # so the second strip was a no-op on it and a clean shortening on the
        # other four. Renaming it to `global_config_path` turned that no-op into
        # a bite, yielding "global" — a key no consumer knows. `_CONTEXT_KEY_MAP`
        # in workspace/manager.py then fell back to "global_path", and
        # `ContextLoader.load_from_paths` rejected the whole context with
        # "Missing config paths: ['global_config_path']", taking every
        # API-driven execution, MLOps and quality route down with it.
        name = _CONFIG_KEY_TO_NAME.get(key, key.removesuffix("_path"))
        result[name] = _resolve_declared_path(base_path, rel_path)

    return result


def _resolve_declared_path(base_path: Path, rel_path: str) -> Path:
    """Confine *rel_path* to *base_path* and resolve it to an existing config file."""
    from ducta.api.utils.git_utils import safe_path  # avoid circular

    resolved = safe_path(base_path, rel_path)

    # If the specified path doesn't exist, probe alternative extensions so
    # projects using .toml / .json configs work without an explicit environment
    # file that spells out the exact extension.
    if not resolved.exists():
        for ext in CONFIG_EXTENSIONS:
            alt = resolved.with_suffix(ext)
            if alt.exists():
                return alt
    return resolved


def find_base_global_config(workspace_root: Path, env: str) -> Path | None:
    """Return the base global config that *env*'s own must be deep-merged over, or None.

    ``find_config_files`` lets an environment's ``global_config_path`` *replace*
    the base one, but the CLI never did that: ``AppConfigManager._merge_base_and_env``
    also hands ``ContextLoader.load_from_paths`` a ``base_global_config_path``,
    which deep-merges the environment's file over the base. Without it, every
    base-only setting — ``spark_config`` above all — silently vanished from
    API-driven runs, so a pipeline that ran under ``ducta start -e dev`` failed
    from the UI. Returns None for ``base`` itself and whenever the environment
    ends up on the same global config as base (nothing to merge).
    """
    from ducta.api.utils.git_utils import safe_path  # avoid circular
    from ducta.api.workspace.loaders import load_environment_yaml  # avoid circular

    if env == "base":
        return None

    env_settings = load_environment_yaml(workspace_root)
    base_gs = env_settings.get("env_config", {}).get("base", {}).get("global_config_path")
    if not base_gs:
        return None

    base_path = safe_path(workspace_root, str(env_settings.get("base_path", ".")))
    base_global = _resolve_declared_path(base_path, base_gs)
    selected = find_config_files(workspace_root, env).get("global_config")
    if selected is None or selected == base_global:
        return None
    return base_global


def find_config_file(directory: Path, stem: str) -> Path | None:
    """Return ``<directory>/<stem>.<ext>`` for the first ext in
    ``CONFIG_EXTENSIONS`` that exists, or None."""
    for ext in CONFIG_EXTENSIONS:
        candidate = directory / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def has_config_file(directory: Path, stem: str) -> bool:
    """Whether *directory* holds ``<stem>`` in any supported config format."""
    return find_config_file(directory, stem) is not None


def find_ducta_config(project_dir: Path) -> Path | None:
    """Return the ``ducta.{yaml,yml,toml,json}`` config file in *project_dir*, if any."""
    return find_config_file(project_dir, "ducta")


def resolve_module_path(workspace_root: Path, module_dotted: str) -> Path:
    """Convert a dotted module path to a ``.py`` file path inside the workspace."""
    from ducta.api.utils.git_utils import safe_path  # avoid circular at top level

    parts = module_dotted.split(".")
    relative = Path(*parts).with_suffix(".py")
    return safe_path(workspace_root, str(relative))


def normalize_workspace_path(path: Path) -> Path:
    """Detect if path is a project directory and return the workspace root instead."""
    path = path.resolve()

    # Rule 1: self-contained workspace (own environment file).
    if has_config_file(path, "environment"):
        return path

    # Rule 2: self-contained workspace (own config/ directory).
    if (path / "config").is_dir():
        return path

    # Rule 3: sub-project under projects/ with no own config — use the workspace root.
    if path.parent.name == "projects":
        return path.parent.parent

    return path
