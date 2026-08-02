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

from ducta.api.exceptions import ConfigFileNotFoundError, NodeNotFoundError
from ducta.api.utils.git_utils import commit_files, file_commit_sha, validate_occ
from ducta.api.workspace.loaders import load_config_file, write_config_file
from ducta.api.workspace.utils import find_config_files, resolve_module_path


def _normalize_node_spec(spec: Dict[str, Any], node_name: Optional[str] = None) -> Dict[str, Any]:
    """Normalize node spec from various formats to frontend-compatible format.

    Converts:
    - TOML format: {input: {...}, output: {...}} → {inputs: [{...}], outputs: [{...}]}
    - Legacy array format: {inputs: [{...}]} → as-is (already compatible)
    - Ensures module and fn have values (with sensible defaults)
    """
    normalized = dict(spec)

    # Convert singular 'input' to plural 'inputs'. A list is already in the
    # expected shape — only a scalar (str/dict) needs wrapping, otherwise we'd
    # produce a nested list like [["bronze.x"]] and the UI loses the real names.
    if "input" in normalized and "inputs" not in normalized:
        input_spec = normalized.pop("input")
        if input_spec:
            normalized["inputs"] = input_spec if isinstance(input_spec, list) else [input_spec]
            logger.debug("Normalized 'input' to 'inputs' array")

    # Convert singular 'output' to plural 'outputs' (same no-double-wrap rule).
    if "output" in normalized and "outputs" not in normalized:
        output_spec = normalized.pop("output")
        if output_spec:
            normalized["outputs"] = output_spec if isinstance(output_spec, list) else [output_spec]
            logger.debug("Normalized 'output' to 'outputs' array")

    # Ensure inputs and outputs are arrays
    if "inputs" in normalized and not isinstance(normalized["inputs"], list):
        normalized["inputs"] = [normalized["inputs"]]
    if "outputs" in normalized and not isinstance(normalized["outputs"], list):
        normalized["outputs"] = [normalized["outputs"]]

    # Streaming nodes declare the Python module under function.module (TOML format):
    #   [silver_clean_events.function]
    #   module = "pipelines.streaming_fraud_realtime"
    # Promote to top-level so resolve_python_file can find the source file.
    if not normalized.get("module") and isinstance(normalized.get("function"), dict):
        fn_module = normalized["function"].get("module")
        if fn_module:
            normalized["module"] = fn_module

    # Ensure module has a value (with sensible default)
    if not normalized.get("module") and node_name:
        normalized["module"] = f"nodes.{node_name}"
        logger.debug(f"Set default module for '{node_name}': {normalized['module']}")

    return normalized


def _find_standard_project_nodes_file(project_dir: Path) -> Optional[Path]:
    """Return the nodes config file for a standard (non-layered) project.

    Resolution order:
    1. Parse environment.* to get the exact ``nodes_config_path`` declared by the project.
    2. Fall back to the convention-based ``config/nodes.*`` path.
    """
    _ENV_EXTS = (".yml", ".yaml", ".toml", ".json")

    # 1. Read environment file to get the declared nodes path
    for ext in _ENV_EXTS:
        env_file = project_dir / f"environment{ext}"
        if env_file.exists():
            try:
                env_data = load_config_file(env_file) or {}
                base_path_str = env_data.get("base_path", ".")
                base_path = (project_dir / base_path_str).resolve()
                nodes_rel = env_data.get("env_config", {}).get("base", {}).get("nodes_config_path")
                if nodes_rel:
                    candidate = (base_path / nodes_rel).resolve()
                    if candidate.exists():
                        return candidate
            except Exception:
                pass
            break  # stop after first env file regardless of outcome

    # 2. Convention-based fallback: config/nodes.*
    for ext in (".yaml", ".yml", ".json", ".toml"):
        candidate = project_dir / "config" / f"nodes{ext}"
        if candidate.exists():
            return candidate

    return None


class NodeRepository:
    """Reads and writes node definitions and associated Python source files."""

    def __init__(self, root: Path) -> None:
        self._root = root

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_path(self) -> Optional[Path]:
        """Return the absolute path to the base nodes config file, or None."""
        base_paths = find_config_files(self._root, "base")
        return base_paths.get("nodes")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_layer_nodes(self) -> Dict[str, Any]:
        """Load node definitions from all projects: layered (ducta.yaml) and standard."""
        layer_nodes: Dict[str, Any] = {}
        projects_dir = self._root / "projects"
        if not projects_dir.is_dir():
            return layer_nodes

        for project_dir in sorted(projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            ducta_file = None
            for ext in (".yaml", ".yml", ".toml", ".json"):
                candidate = project_dir / f"ducta{ext}"
                if candidate.exists():
                    ducta_file = candidate
                    break

            if ducta_file:
                # Layered project: load nodes from each layer defined in ducta.yaml
                try:
                    ducta_config = load_config_file(ducta_file)
                    layers = ducta_config.get("layers", {})
                    for layer_name, layer_cfg in layers.items():
                        nodes_path = layer_cfg.get("nodes")
                        if not nodes_path:
                            config_dir = layer_cfg.get("config")
                            if config_dir:
                                nodes_path = str(Path(config_dir) / "nodes.yaml")
                        if not nodes_path:
                            continue
                        full_path = project_dir / nodes_path
                        if not full_path.exists():
                            continue
                        try:
                            raw = load_config_file(full_path) or {}
                            for node_key, node_spec in raw.items():
                                # Avoid double-prefix: node keys in nodes.yaml may
                                # already carry the layer prefix (e.g. "silver.foo").
                                if node_key.startswith(f"{layer_name}."):
                                    prefixed_name = node_key
                                else:
                                    prefixed_name = f"{layer_name}.{node_key}"
                                normalized = _normalize_node_spec(dict(node_spec))
                                # Preserve the module declared in the spec; only
                                # fall back to a derived name when absent.
                                if not normalized.get("module"):
                                    normalized["module"] = f"src.{node_key.split('.')[-1]}"
                                layer_nodes[prefixed_name] = normalized
                            logger.debug(
                                "Loaded {count} nodes from layer '{layer}' in project '{proj}'",
                                count=len(raw),
                                layer=layer_name,
                                proj=project_dir.name,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Failed to load layer nodes for '{proj}/{layer}': {exc}",
                                proj=project_dir.name,
                                layer=layer_name,
                                exc=exc,
                            )
                except Exception as exc:
                    logger.warning(
                        "Failed to read ducta config for '{proj}': {exc}",
                        proj=project_dir.name,
                        exc=exc,
                    )
            else:
                # Standard project (no ducta.yaml): resolve nodes file via the
                # environment file first (handles custom paths like base/node/nodes.yml
                # or config/streaming/nodes.toml), then fall back to config/nodes.*.
                nodes_file = _find_standard_project_nodes_file(project_dir)
                if not nodes_file:
                    continue
                try:
                    raw = load_config_file(nodes_file) or {}
                    for node_key, node_spec in raw.items():
                        normalized = _normalize_node_spec(dict(node_spec), node_name=node_key)
                        layer_nodes[node_key] = normalized
                    logger.debug(
                        "Loaded {count} nodes from standard project '{proj}' ({file})",
                        count=len(raw),
                        proj=project_dir.name,
                        file=nodes_file.name,
                    )
                except Exception as exc:
                    logger.debug(
                        "Failed to load nodes for standard project '{proj}': {exc}",
                        proj=project_dir.name,
                        exc=exc,
                    )

        return layer_nodes

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_file_path(self) -> Optional[Path]:
        """Expose the config file path for external callers."""
        return self._get_path()

    def list_all(self) -> Dict[str, Any]:
        """Return all node definitions keyed by name, normalized to frontend format.

        Merges nodes from the base environment config with nodes from project
        layer configs (defined via ducta.yaml). Project layer nodes are prefixed
        with ``{layer_name}.`` (e.g. ``bronze.intl_results``).
        """
        nodes: Dict[str, Any] = {}

        # 1. Load base environment nodes
        path = self._get_path()
        if path and path.exists():
            base_nodes = load_config_file(path) or {}
            for name, spec in base_nodes.items():
                nodes[name] = _normalize_node_spec(spec, node_name=name)

        # 2. Load project layer nodes
        layer_nodes = self._load_layer_nodes()
        # Layer nodes take precedence over base nodes with the same name
        nodes.update(layer_nodes)

        return nodes

    def get(self, name: str) -> Dict[str, Any]:
        """Return the spec for a single node.

        Raises :exc:`NodeNotFoundError` when the node is absent.
        """
        nodes = self.list_all()
        if name not in nodes:
            raise NodeNotFoundError(
                f"Node '{name}' not found",
                detail={"name": name},
            )
        return nodes[name]

    def get_commit_sha(self) -> str:
        """Return the short SHA of the latest commit that modified the nodes config file."""
        path = self._get_path()
        if path is None:
            return ""
        return file_commit_sha(self._root, path)

    def resolve_python_file(self, name: str) -> Path:
        """Return the absolute ``.py`` path for a node's Python source.

        Searches in order:
        1. Workspace root (flat layout)
        2. Project sub-directories (standard project layout)
        3. Project layer ``src/`` directories (layered project layout)
        """
        nodes = self.list_all()
        if name not in nodes:
            raise NodeNotFoundError(
                f"Node '{name}' not found in nodes.yaml",
                detail={"name": name},
            )
        spec = nodes[name]
        module_dotted: Optional[str] = spec.get("module") or f"nodes.{name}"

        py_path = resolve_module_path(self._root, module_dotted)
        if py_path.exists():
            return py_path

        projects_dir = self._root / "projects"
        if not projects_dir.is_dir():
            return py_path

        # Search project directories for the file
        for project_dir in sorted(projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            try:
                candidate = resolve_module_path(project_dir, module_dotted)
                if candidate.exists():
                    logger.debug(
                        "Node file found in project sub-dir: {path}",
                        path=candidate,
                    )
                    return candidate
            except ValueError:
                pass

            # Also search layer src/ directories (layered projects)
            try:
                ducta_file = None
                for ext in (".yaml", ".yml", ".toml", ".json"):
                    candidate = project_dir / f"ducta{ext}"
                    if candidate.exists():
                        ducta_file = candidate
                        break
                if not ducta_file:
                    continue
                ducta_config = load_config_file(ducta_file)
                layers = ducta_config.get("layers", {})
                for layer_name, layer_cfg in layers.items():
                    layer_path_str = layer_cfg.get("path", layer_name)
                    layer_dir = project_dir / layer_path_str
                    if not layer_dir.is_dir():
                        continue
                    try:
                        layer_candidate = resolve_module_path(layer_dir, module_dotted)
                        if layer_candidate.exists():
                            logger.debug(
                                "Node file found in layer sub-dir: {path}",
                                path=layer_candidate,
                            )
                            return layer_candidate
                    except ValueError:
                        pass
            except Exception:
                continue

        return py_path

    # ── Commands ──────────────────────────────────────────────────────────────

    def save(
        self,
        name: str,
        spec: Dict[str, Any],
        expected_sha: Optional[str] = None,
    ) -> str:
        """Update or create a node entry and git-commit.

        Returns the new commit SHA (empty string when git is unavailable).
        """
        path = self._get_path()
        if path is None:
            raise ConfigFileNotFoundError(
                "Nodes config file not found in base environment",
                detail={"env": "base"},
            )
        validate_occ(self._root, path, expected_sha)
        current = load_config_file(path) if path.exists() else {}
        current[name] = spec
        write_config_file(path, current)
        return commit_files(self._root, [path], f"chore: update node '{name}'")

    def delete(self, name: str, expected_sha: Optional[str] = None) -> str:
        """Remove a node entry and git-commit.

        Raises :exc:`NodeNotFoundError` when the node is absent.
        Raises :exc:`ConcurrencyError` (via ``validate_occ``) when
        *expected_sha* is given and the file was modified since — the same
        check ``save()`` already applies, but ``delete()`` used to skip it
        entirely, so a delete could silently discard a change made
        concurrently by someone else.
        Returns the new commit SHA (empty string when git is unavailable).
        """
        path = self._get_path()
        if path is None:
            raise ConfigFileNotFoundError(
                "Nodes config file not found in base environment",
                detail={"env": "base"},
            )
        validate_occ(self._root, path, expected_sha)
        current = load_config_file(path) if path.exists() else {}
        if name not in current:
            raise NodeNotFoundError(
                f"Node '{name}' not found",
                detail={"name": name},
            )
        del current[name]
        write_config_file(path, current)
        return commit_files(self._root, [path], f"chore: delete node '{name}'")
