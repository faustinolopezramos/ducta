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
from typing import Any, Iterable, Optional

# URI scheme prefixes that should never be treated as local paths
_URI_PREFIXES: tuple[str, ...] = (
    "s3://",
    "s3a://",
    "s3n://",
    "gs://",
    "abfss://",
    "abfs://",
    "dbfs:/",
    "file:/",
    "http://",
    "https://",
)


def _looks_like_uri(value: str) -> bool:
    return value.strip().lower().startswith(_URI_PREFIXES)


def _absolutize_path_value(value: Any, base_dir: Path) -> Optional[str]:
    """Return an absolute string path for *value* resolved against *base_dir*.

    Returns *None* when *value* is not a string or is a URI.
    """
    if not isinstance(value, str):
        return None
    raw_value = value.strip()
    if not raw_value or _looks_like_uri(raw_value) or "${" in raw_value:
        return value  # a URI, or a placeholder resolved later
    candidate = Path(raw_value)
    if candidate.is_absolute():
        return str(candidate)
    return str((base_dir / candidate).resolve())


def _normalize_nested_paths(value: Any, path_keys: set[str], base_dir: Path) -> Any:
    if isinstance(value, dict):
        for key, nested_value in list(value.items()):
            if key in path_keys:
                normalized = _absolutize_path_value(nested_value, base_dir)
                if normalized is not None:
                    value[key] = normalized
                    continue
            _normalize_nested_paths(nested_value, path_keys, base_dir)
        return value
    if isinstance(value, list):
        for item in value:
            _normalize_nested_paths(item, path_keys, base_dir)
    return value


def _normalize_config_mapping(
    config_mapping: Any,
    *,
    path_keys: Iterable[str],
    base_dir: Path,
) -> None:
    if not isinstance(config_mapping, dict):
        return
    path_key_set = set(path_keys)
    for config in config_mapping.values():
        _normalize_nested_paths(config, path_key_set, base_dir)


def normalize_execution_context_paths(ctx: Any, base_dir: Path) -> None:
    """Absolutise all relative filesystem paths in the execution *ctx*."""
    for path_attr in ("input_path", "output_path"):
        value = getattr(ctx, path_attr, None)
        normalized = _absolutize_path_value(value, base_dir)
        if normalized is not None and normalized != value:
            setattr(ctx, path_attr, normalized)

    global_config = getattr(ctx, "global_config", None)
    if isinstance(global_config, dict):
        for path_key in ("input_path", "output_path", "model_registry_path", "mlops_path"):
            value = global_config.get(path_key)
            normalized = _absolutize_path_value(value, base_dir)
            if normalized is not None and normalized != value:
                global_config[path_key] = normalized

    _normalize_config_mapping(
        getattr(ctx, "input_config", None),
        path_keys=("filepath", "path"),
        base_dir=base_dir,
    )
    _normalize_config_mapping(
        getattr(ctx, "output_config", None),
        path_keys=("filepath", "path", "checkpointLocation", "schemaLocation"),
        base_dir=base_dir,
    )

    nodes_config = getattr(ctx, "nodes_config", None)
    if isinstance(nodes_config, dict):
        _normalize_config_mapping(
            {
                name: node
                for name, node in nodes_config.items()
                if isinstance(node, dict) and node.get("type") == "streaming"
            },
            path_keys=(
                "path",
                "checkpoint_location",
                "checkpointLocation",
                "schemaLocation",
            ),
            base_dir=base_dir,
        )


def select_execution_cwd(source_path: Path, env_dir: Path, ctx: Any) -> Path:
    """Choose the best working directory for the execution."""
    global_config = getattr(ctx, "global_config", {}) or {}
    candidate_paths = [
        global_config.get("input_path"),
        global_config.get("output_path"),
    ]
    relative_paths = [
        Path(str(v))
        for v in candidate_paths
        if isinstance(v, str) and v.strip() and not Path(str(v)).is_absolute()
    ]
    if not relative_paths:
        return source_path

    root_matches = sum(1 for p in relative_paths if (source_path / p).exists())
    env_matches = sum(1 for p in relative_paths if (env_dir / p).exists())

    if root_matches > 0 and root_matches >= env_matches:
        return source_path
    if env_matches > root_matches:
        return env_dir
    return source_path


def load_project_context(path: Path, env: str) -> Any:
    """The Context of the project at (or owning) *path* for *env*, as server runs
    load it: never importing Python from configuration (``allow_python_config=False``),
    and stamped with the workspace it belongs to (see :func:`stamp_context`).
    """
    from ducta.project_store.errors import ValidationError, WorkspaceNotFoundError
    from ducta.setting.project.loader import find_project_root, load_project_v2
    from ducta.setting.workspace import normalize_workspace_path

    original = Path(path).resolve()
    workspace = normalize_workspace_path(original)
    if not workspace.is_dir():
        raise WorkspaceNotFoundError(
            f"Directory not found: {workspace}", detail={"path": str(workspace)}
        )
    candidates = [original, workspace] if original != workspace else [workspace]
    project_root = next(
        (found for found in map(find_project_root, candidates) if found is not None), None
    )
    if project_root is None:
        from ducta.setting.project.reader import other_format

        target = candidates[0]
        raise ValidationError(
            other_format(target) or f"No Ducta project (ducta.yaml, version 2) in {target}"
        )
    ctx = load_project_v2(project_root, env, allow_python_config=False)
    stamp_context(ctx, workspace, env)
    return ctx


def stamp_context(ctx: Any, workspace: Path, env: str) -> None:
    """Record on *ctx* the workspace it was loaded from and the directory its
    relative paths resolve against (``<workspace>/<env>`` when that exists)."""
    env_dir = workspace / env if (workspace / env).is_dir() else workspace
    for attr, value in (
        ("workspace_root", workspace),
        ("source_path", workspace),
        ("env_dir", env_dir),
        ("path_resolution_base", env_dir),
    ):
        try:
            setattr(ctx, attr, value)
        except Exception:  # noqa: BLE001 — a context that refuses an attribute keeps its own
            pass
