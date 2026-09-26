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
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from ducta.api.exceptions import NodeNotFoundError
from ducta.api.repositories._yaml_record_repository import YamlRecordRepository
from ducta.api.utils.git_utils import file_commit_sha
from ducta.api.workspace.loaders import load_config_file
from ducta.api.workspace.utils import find_config_file, find_ducta_config, resolve_module_path


def _normalize_node_spec(spec: Dict[str, Any], node_name: Optional[str] = None) -> Dict[str, Any]:
    """Normalize node spec from various formats to frontend-compatible format."""
    normalized = dict(spec)

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
    """Return the nodes config file for a standard (non-layered) project."""
    # 1. Read environment file to get the declared nodes path
    env_file = find_config_file(project_dir, "environment")
    if env_file is not None:
        try:
            env_data = load_config_file(env_file) or {}
            base_path = (project_dir / env_data.get("base_path", ".")).resolve()
            nodes_rel = env_data.get("env_config", {}).get("base", {}).get("nodes_config_path")
            if nodes_rel:
                candidate = (base_path / nodes_rel).resolve()
                if candidate.exists():
                    return candidate
        except Exception:
            pass

    # 2. Convention-based fallback: config/nodes.*
    return find_config_file(project_dir / "config", "nodes")


class NodeRepository(YamlRecordRepository):
    """Reads and writes node definitions and associated Python source files."""

    _config_key = "nodes"
    _not_found_error = NodeNotFoundError
    _config_label = "Nodes"
    _action_label = "node"

    def __init__(self, root: Path) -> None:
        self._root = root
        self._node_source: Dict[str, Tuple[Path, Optional[str]]] = {}

    def _load_layer_nodes(self) -> Tuple[Dict[str, Any], Dict[str, Tuple[Path, Optional[str]]]]:
        """Load node definitions from all projects: layered (ducta.yaml) and standard."""
        layer_nodes: Dict[str, Any] = {}
        layer_sources: Dict[str, Tuple[Path, Optional[str]]] = {}
        projects_dir = self._root / "projects"
        if not projects_dir.is_dir():
            return layer_nodes, layer_sources

        for project_dir in sorted(projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            ducta_file = find_ducta_config(project_dir)

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
                                record_key = node_key if node_key != prefixed_name else None
                                layer_sources[prefixed_name] = (full_path, record_key)
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
                nodes_file = _find_standard_project_nodes_file(project_dir)
                if not nodes_file:
                    continue
                try:
                    raw = load_config_file(nodes_file) or {}
                    for node_key, node_spec in raw.items():
                        normalized = _normalize_node_spec(dict(node_spec), node_name=node_key)
                        layer_nodes[node_key] = normalized
                        layer_sources[node_key] = (nodes_file, None)
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

        return layer_nodes, layer_sources

    def list_all(self) -> Dict[str, Any]:
        """Return all node definitions keyed by name, normalized to frontend format."""
        nodes: Dict[str, Any] = {}
        sources: Dict[str, Tuple[Path, Optional[str]]] = {}

        # 1. Load base environment nodes
        base_path = self._get_path()
        base_nodes = super().list_all()
        for name, spec in base_nodes.items():
            nodes[name] = _normalize_node_spec(spec, node_name=name)
            if base_path is not None:
                sources[name] = (base_path, None)

        # 2. Load project layer nodes
        layer_nodes, layer_sources = self._load_layer_nodes()
        # Layer nodes take precedence over base nodes with the same name
        nodes.update(layer_nodes)
        sources.update(layer_sources)

        self._node_source = sources
        return nodes

    def get_commit_sha(self) -> str:
        """Return the short SHA of the latest commit that modified the nodes config file."""
        path = self._get_path()
        if path is None:
            return ""
        return file_commit_sha(self._root, path)

    def resolve_python_file(self, name: str) -> Path:
        """Return the absolute ``.py`` path for a node's Python source."""
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
                ducta_file = find_ducta_config(project_dir)
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

    def _fast_locate_layer_node(self, name: str) -> Optional[Tuple[Path, Optional[str]]]:
        """Resolve a dotted ``layer.node`` name's file without scanning every
        project's node registry (see ``_load_layer_nodes``).

        Only project ``ducta.yaml`` files are read here (cheap — no node specs
        parsed) to find the layer whose name prefixes *name*; only that one
        layer's nodes file is then parsed. Returns ``None`` when *name* has no
        dotted layer prefix or no matching layer is found, so callers can fall
        back to the exhaustive :meth:`list_all` scan.
        """
        if "." not in name:
            return None
        projects_dir = self._root / "projects"
        if not projects_dir.is_dir():
            return None
        for project_dir in sorted(projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            ducta_file = find_ducta_config(project_dir)
            if not ducta_file:
                continue
            try:
                layers = load_config_file(ducta_file).get("layers", {})
            except Exception:
                continue
            for layer_name, layer_cfg in layers.items():
                if not name.startswith(f"{layer_name}."):
                    continue
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
                except Exception:
                    continue
                if name in raw:
                    return full_path, None
                node_key = name[len(layer_name) + 1 :]
                if node_key in raw:
                    return full_path, node_key
        return None

    def _locate_source(self, name: str) -> Tuple[Optional[Path], Optional[str]]:
        fast = self._fast_locate_layer_node(name)
        if fast is not None:
            return fast
        if not self._node_source:
            self.list_all()
        target = self._node_source.get(name)
        return target if target else (None, None)

    def save(self, name: str, spec: Dict[str, Any], expected_sha: Optional[str] = None) -> str:
        """Update or create a node, writing back to wherever it actually lives."""
        path, record_key = self._locate_source(name)
        return super().save(name, spec, expected_sha, path=path, record_key=record_key)

    def delete(self, name: str, expected_sha: Optional[str] = None) -> str:
        """Delete a node from wherever it actually lives (see ``save``)."""
        path, record_key = self._locate_source(name)
        return super().delete(name, expected_sha, path=path, record_key=record_key)
