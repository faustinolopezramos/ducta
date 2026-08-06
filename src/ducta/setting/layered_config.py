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

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Set

from loguru import logger

from ducta.setting.loaders import ConfigLoaderFactory

__all__ = [
    "LayerConfig",
    "LayerContextBuilder",
    "LayeredExecutionResult",
    "LayeredProjectDetector",
    "detect_and_prepare_layered_execution",
    "layer_sys_path",
]

# Declarative layered-project manifest, probed in extension precedence order.
_MANIFEST_STEMS = ("ducta",)
_MANIFEST_EXTS = (".yaml", ".yml", ".toml", ".json")


def _find_manifest(root: Path) -> Optional[Path]:
    """Return the first ``ducta.<ext>`` manifest file in ``root``, if any."""
    for stem in _MANIFEST_STEMS:
        for ext in _MANIFEST_EXTS:
            candidate = root / f"{stem}{ext}"
            if candidate.is_file():
                return candidate
    return None


def _load_manifest(path: Path) -> Optional[Dict]:
    """Best-effort load of a manifest file; returns None on failure."""
    try:
        return ConfigLoaderFactory().load_config(str(path))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Could not load layered manifest '{}': {}", path, exc)
        return None


def _relativize(config_value: str, layer_path: str) -> str:
    """Normalize a layer's ``config`` path to be relative to its ``path``.

    ``ducta.yaml`` layers commonly express ``config`` from the project root
    (``config: bronze/config`` for ``path: bronze``); ``LayerConfig`` expects it
    relative to the layer directory. Strips the leading layer prefix when
    present, otherwise returns the value unchanged.
    """
    config_path = Path(config_value)
    try:
        return str(config_path.relative_to(layer_path))
    except ValueError:
        return config_value


class LayerConfig:
    """Represents a single layer configuration."""

    def __init__(self, name: str, config_dict: Dict) -> None:
        self.name = name
        self.path = Path(config_dict.get("path", name))
        self.description = config_dict.get("description", "")
        self.depends_on = config_dict.get("depends_on", [])
        self.global_settings = config_dict.get("global_settings", "global.yaml")
        self.config_path = config_dict.get("config_path", "config")

    def get_config_paths(self, base_path: Path) -> Dict[str, Path]:
        """Get absolute paths for all config files in this layer."""
        layer_path = base_path / self.path

        return {
            "global_settings": layer_path / self.global_settings,
            "pipelines_config": layer_path / self.config_path / "pipelines.yaml",
            "nodes_config": layer_path / self.config_path / "nodes.yaml",
            "input_config": layer_path / self.config_path / "input.yaml",
            "output_config": layer_path / self.config_path / "output.yaml",
            "layer_path": layer_path,
        }

    def get_pipeline_names(self, base_path: Path) -> Set[str]:
        """Return the set of top-level pipeline keys in this layer's pipelines.yaml.

        Best-effort: returns an empty set (never raises) if the file is missing,
        unreadable, malformed, or not a mapping — this is a detection helper,
        not a validation gate.
        """
        pipelines_path = self.get_config_paths(base_path)["pipelines_config"]
        if not pipelines_path.exists():
            return set()
        try:
            data = ConfigLoaderFactory().load_config(str(pipelines_path))
        except Exception as e:
            logger.debug(f"Could not read pipelines config for layer '{self.name}': {e}")
            return set()
        return set(data.keys()) if isinstance(data, dict) else set()


class LayeredProjectDetector:
    """Detects and manages layered project configurations."""

    SETTINGS_FILE = ".ducta/settings.json"
    DEFAULT_LAYER_NAMES = ["bronze", "silver", "gold", "ml"]  # Standard medallion architecture

    def __init__(self, project_root: Optional[Path] = None) -> None:
        if project_root is None:
            project_root = Path.cwd()
        self.project_root = project_root
        self.settings_file = project_root / self.SETTINGS_FILE
        self.is_layered_project = False
        self.layers: Dict[str, LayerConfig] = {}
        self.execution_order: List[str] = []

        # Resolution order: explicit .ducta/settings.json → declarative ducta.yaml
        # (arbitrary layer names) → convention auto-detection.
        #
        # Each step must fall through when it yields no layers, not merely when
        # its source is absent: a settings file that exists but declares no
        # `layers` is not evidence that the project is flat, and must not
        # suppress the manifest and auto-detection that follow it.
        if self.settings_file.exists():
            self._load_settings()
        if not self.is_layered_project and self._load_ducta_yaml():
            logger.info("Loaded layered project structure from ducta.* manifest")
            self.is_layered_project = True
        if not self.is_layered_project and self._auto_detect_layers():
            logger.info("Auto-detected layered project structure (no settings file needed)")
            self.is_layered_project = True

    def _auto_detect_layers(self) -> bool:
        """Auto-detect layered structure by looking for standard layer directories.

        Looks for directories like bronze/, silver/, gold/, ml/ with valid configs.

        Returns:
            True if valid layered structure detected
        """
        detected_layers = []

        for layer_name in self.DEFAULT_LAYER_NAMES:
            layer_path = self.project_root / layer_name
            global_settings = layer_path / "global.yaml"
            config_dir = layer_path / "config"

            # Check if this looks like a valid layer
            if layer_path.is_dir() and global_settings.exists() and config_dir.is_dir():
                detected_layers.append(layer_name)
                # Create layer config automatically
                layer_config = {
                    "path": layer_name,
                    "global_settings": "global.yaml",
                    "config_path": "config",
                    "description": f"Layer: {layer_name}",
                }
                self.layers[layer_name] = LayerConfig(layer_name, layer_config)

        if not detected_layers:
            return False

        # Set execution order based on detected layers (in standard order)
        self.execution_order = [
            layer for layer in self.DEFAULT_LAYER_NAMES if layer in detected_layers
        ]

        # Set dependencies (each layer depends on the previous one)
        for i, layer_name in enumerate(detected_layers):
            if i > 0:
                self.layers[layer_name].depends_on = [detected_layers[i - 1]]

        logger.debug(f"Auto-detected layers: {detected_layers}")
        return len(detected_layers) > 0

    def _load_settings(self) -> None:
        """Load and parse layer settings from .ducta/settings.json."""
        try:
            with open(self.settings_file) as f:
                settings = json.load(f)

            ducta_config = settings.get("ducta", {})
            layers_config = ducta_config.get("layers", [])
            self.execution_order = ducta_config.get("execution_order", [])

            for layer_def in layers_config:
                name = layer_def.get("name")
                if name:
                    self.layers[name] = LayerConfig(name, layer_def)

            self.is_layered_project = bool(self.layers)
            logger.debug(f"Loaded {len(self.layers)} layers: {list(self.layers.keys())}")

        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load layered config: {e}")
            self.is_layered_project = False

    def _load_ducta_yaml(self) -> bool:
        """Load layer definitions from a declarative ``ducta.*`` manifest.

        The manifest opts in with ``project.type: layered`` and declares a
        ``layers`` mapping (arbitrary names, not just the medallion defaults),
        e.g.::

            project: {type: layered}
            layers:
              raw:      {path: raw,      config: raw/config,      dependencies: []}
              curated:  {path: curated,  config: curated/config,  dependencies: [raw]}
            execution: {order: [raw, curated]}

        Each layer's ``config`` is normalized to a path *relative to the layer*
        (``LayerConfig`` joins ``base/<path>/<config_path>/pipelines.yaml``), so
        both ``config: raw/config`` and ``config: config`` resolve correctly.
        Returns ``False`` (leaving the detector untouched) when no manifest
        exists or it is not a layered project, so the caller can fall back to
        convention auto-detection.
        """
        manifest = _find_manifest(self.project_root)
        if manifest is None:
            return False

        data = _load_manifest(manifest)
        if not isinstance(data, dict):
            return False

        project = data.get("project") or {}
        if str(project.get("type", "")).strip().lower() != "layered":
            return False  # e.g. a single-file bundle named ducta.* — not layered

        layers = data.get("layers") or {}
        if not isinstance(layers, dict) or not layers:
            return False

        for name, layer_def in layers.items():
            if not isinstance(layer_def, dict):
                continue
            layer_path = layer_def.get("path", name)
            config_value = layer_def.get("config", "config")
            config_rel = _relativize(config_value, layer_path)
            self.layers[name] = LayerConfig(
                name,
                {
                    "path": layer_path,
                    "global_settings": layer_def.get("global_settings", "global.yaml"),
                    "config_path": config_rel,
                    "description": layer_def.get("description", ""),
                    "depends_on": layer_def.get("dependencies", []) or [],
                },
            )

        if not self.layers:
            return False

        execution = data.get("execution") or {}
        self.execution_order = list(execution.get("order") or self.layers.keys())
        logger.debug(
            "Loaded {} layer(s) from {}: {}",
            len(self.layers),
            manifest.name,
            list(self.layers.keys()),
        )
        return True

    def get_layer(self, layer_name: str) -> Optional[LayerConfig]:
        """Get a specific layer configuration."""
        return self.layers.get(layer_name)

    def list_layers(self) -> List[str]:
        """List all available layers."""
        return list(self.layers.keys())

    def get_execution_order(self) -> List[str]:
        """Get layers in execution order."""
        return self.execution_order

    def validate_layer_exists(self, layer_name: str) -> bool:
        """Validate that a layer exists."""
        return layer_name in self.layers

    def find_layers_for_pipeline(self, pipeline_name: str) -> List[str]:
        """Return layer names whose pipelines.yaml contains pipeline_name as a key.

        Iterates in execution_order (falls back to dict insertion order) for
        deterministic, reproducible results across calls.
        """
        layer_order = self.execution_order or list(self.layers.keys())
        matches = []
        for layer_name in layer_order:
            layer = self.layers.get(layer_name)
            if layer and pipeline_name in layer.get_pipeline_names(self.project_root):
                matches.append(layer_name)
        return matches

    def validate_execution_order(self) -> bool:
        """Validate that execution order respects dependencies."""
        seen = set()
        for layer_name in self.execution_order:
            layer = self.layers.get(layer_name)
            if not layer:
                logger.error(f"Layer '{layer_name}' in execution_order not defined")
                return False

            for dep in layer.depends_on:
                if dep not in seen:
                    logger.error(
                        f"Layer '{layer_name}' depends on '{dep}' which hasn't been "
                        f"executed yet. Execution order: {self.execution_order}"
                    )
                    return False

            seen.add(layer_name)

        return True


class LayerContextBuilder:
    """Builds Ducta Context objects for layered configurations."""

    @staticmethod
    def build_context_args(
        detector: LayeredProjectDetector, layer_name: str, env: str = "base"
    ) -> Optional[Dict]:
        """Build context arguments for a specific layer.

        ``env`` is returned in the dict rather than merely accepted: the caller
        has to pass it on to ``Context(env=...)``, and when it was only a
        parameter this method ignored, at least one caller
        (``ducta config validate``) resolved an environment, handed it here, and
        then built its Context without one — validating a layered project
        against its base configuration whatever ``--env`` said.

        Returns:
            Dictionary with keys: global_settings, pipelines_config, nodes_config,
                                 input_config, output_config, layer, layer_path, env.
            Or None if layer not found or paths don't exist.
        """
        layer = detector.get_layer(layer_name)
        if not layer:
            logger.error(f"Layer '{layer_name}' not found")
            return None

        config_paths = layer.get_config_paths(detector.project_root)

        # Verify all required files exist
        required_files = [
            "global_settings",
            "pipelines_config",
            "nodes_config",
            "input_config",
            "output_config",
        ]

        for file_key in required_files:
            if not config_paths[file_key].exists():
                logger.error(f"Missing {file_key}: {config_paths[file_key]}")
                return None

        return {
            "global_settings": str(config_paths["global_settings"]),
            "pipelines_config": str(config_paths["pipelines_config"]),
            "nodes_config": str(config_paths["nodes_config"]),
            "input_config": str(config_paths["input_config"]),
            "output_config": str(config_paths["output_config"]),
            "layer": layer_name,
            "layer_path": str(config_paths["layer_path"]),
            "env": env,
        }

    @staticmethod
    def layer_import_roots(detector: LayeredProjectDetector, layer_name: str) -> List[str]:
        """The paths a layer's node functions are imported from, front of path first."""
        layer = detector.get_layer(layer_name)
        if not layer:
            return []

        roots = []
        layer_root = (detector.project_root / layer.path).resolve()
        layer_src = layer_root / "src"
        # The layer root first, so `import src.foo` resolves to *this* layer's
        # `src` package before Python can cache the workspace root's `src` as a
        # namespace package.
        if layer_root.is_dir():
            roots.append(str(layer_root))
        if layer_src.is_dir():
            roots.append(str(layer_src))
        return roots

    @staticmethod
    def inject_sys_path(detector: LayeredProjectDetector, layer_name: str) -> None:
        """Add a layer's import roots to ``sys.path``, permanently.

        Prefer :func:`layer_sys_path` where the scope is known. This remains for
        callers that run a single layer and then exit.
        """
        for root in reversed(LayerContextBuilder.layer_import_roots(detector, layer_name)):
            if root not in sys.path:
                sys.path.insert(0, root)
                logger.debug("Added {} to sys.path", root)


@contextmanager
def layer_sys_path(detector: "LayeredProjectDetector", layer_name: str) -> Iterator[None]:
    """Make a layer importable for the duration of the block, then undo it.

    ``inject_sys_path`` only ever added. Every layer names its package ``src``,
    so running more than one layer in a process (``--all-layers``, the API
    serving two layered projects) left each layer's directory stacked on
    ``sys.path`` with a stale ``sys.modules['src']`` pointing at whichever ran
    first — after which the second layer silently imported the first layer's
    node functions.

    Restores ``sys.path`` and drops the modules that were imported from the
    roots this block added, so the next layer resolves its own.
    """
    roots = LayerContextBuilder.layer_import_roots(detector, layer_name)
    added = [root for root in roots if root not in sys.path]
    for root in reversed(added):
        sys.path.insert(0, root)
        logger.debug("Added {} to sys.path", root)

    before = set(sys.modules)
    try:
        yield
    finally:
        for root in added:
            try:
                sys.path.remove(root)
            except ValueError:  # pragma: no cover - someone else removed it
                pass
        for name in set(sys.modules) - before:
            module_file = getattr(sys.modules.get(name), "__file__", None) or ""
            if any(module_file.startswith(root) for root in added):
                sys.modules.pop(name, None)
            elif name == "src" or name.startswith("src."):
                # Namespace packages have no __file__ to attribute.
                sys.modules.pop(name, None)


class LayeredExecutionResult(NamedTuple):
    is_layered: bool
    execution_type: Optional[str]
    context_args: Dict


def detect_and_prepare_layered_execution(
    parsed_args,
) -> LayeredExecutionResult:
    """
    Detects layered project and prepares context arguments.
    """
    detector = LayeredProjectDetector()

    if not detector.is_layered_project:
        return LayeredExecutionResult(False, None, {})

    # Validate execution order
    if not detector.validate_execution_order():
        logger.error("Invalid layer execution order")
        return LayeredExecutionResult(True, None, {})

    # Check for --all-layers flag
    if hasattr(parsed_args, "all_layers") and parsed_args.all_layers:
        return LayeredExecutionResult(True, "all", {})

    # Check for --layer flag (explicit routing)
    if hasattr(parsed_args, "layer") and parsed_args.layer:
        layer_name = parsed_args.layer

        if not detector.validate_layer_exists(layer_name):
            available = ", ".join(detector.list_layers())
            logger.error(
                f"Layer '{layer_name}' not found.\n"
                f"Available layers: {available}\n\n"
                f"Try renaming your pipeline to use unique names per layer,\n"
                f"or use --all-layers to execute all layers."
            )
            return LayeredExecutionResult(True, None, {})

        context_args = LayerContextBuilder.build_context_args(detector, layer_name, parsed_args.env)
        if not context_args:
            return LayeredExecutionResult(True, None, {})

        # Inject sys.path for module discovery
        LayerContextBuilder.inject_sys_path(detector, layer_name)

        return LayeredExecutionResult(True, "single", context_args)

    # Auto-detect: --pipeline given, --layer omitted
    pipeline_name = getattr(parsed_args, "pipeline", None)
    if pipeline_name:
        matching_layers = detector.find_layers_for_pipeline(pipeline_name)

        if len(matching_layers) == 1:
            layer_name = matching_layers[0]
            logger.info(
                f"Auto-detected layer '{layer_name}' for pipeline '{pipeline_name}' "
                f"(no --layer flag provided)"
            )
            context_args = LayerContextBuilder.build_context_args(
                detector, layer_name, parsed_args.env
            )
            if not context_args:
                logger.warning(
                    f"Layer '{layer_name}' matched pipeline '{pipeline_name}' but its "
                    f"config files are incomplete; falling back to flat-mode discovery"
                )
                return LayeredExecutionResult(True, None, {})
            LayerContextBuilder.inject_sys_path(detector, layer_name)
            return LayeredExecutionResult(True, "single", context_args)

        if len(matching_layers) > 1:
            # Ambiguous match: error with suggested command
            layers_str = ", ".join(matching_layers)
            suggested_layer = matching_layers[0]
            logger.error(
                f"Pipeline '{pipeline_name}' is ambiguous: found in multiple layers [{layers_str}].\n"
                f"Cannot auto-route without disambiguation.\n\n"
                f"Try one of:\n"
                f"  ducta start --layer {suggested_layer} --env {parsed_args.env} --pipeline {pipeline_name}\n"
                f"Or use --all-layers to execute all layers in order."
            )
            return LayeredExecutionResult(True, None, {})

        logger.debug(
            f"Pipeline '{pipeline_name}' not found in any layer's pipelines.yaml "
            f"({detector.list_layers()}); falling back to flat-mode config discovery"
        )

    return LayeredExecutionResult(True, None, {})
