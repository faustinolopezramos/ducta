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

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger  # type: ignore

from ducta.check import QualityOutputPath
from ducta.mlrun.hyperparams import HyperparamConfig, load_hyperparams_config
from ducta.setting.exceptions import ConfigLoadError, ConfigValidationError
from ducta.setting.interpolator import VariableInterpolator
from ducta.setting.loaders import ConfigLoaderFactory
from ducta.setting.schemas import ConfigSchema
from ducta.setting.session import SparkSessionFactory
from ducta.setting.utils import deep_merge_dicts as _deep_merge_dicts
from ducta.setting.validators import (
    ConfigValidator,
    FormatPolicy,
    HybridValidator,
    MLValidator,
    PipelineValidator,
    StreamingValidator,
)


class PipelineManager:
    """Manages pipeline configurations and operations."""

    def __init__(self, pipelines_config: Dict[str, Any], nodes_config: Dict[str, Any]):
        self.pipelines_config = pipelines_config
        self.nodes_config = nodes_config
        self._validator = PipelineValidator()

    @cached_property
    def pipelines(self) -> Dict[str, Dict[str, Any]]:
        """Return all loaded and validated pipeline configurations."""
        self._validator.validate_pipeline_nodes(self.pipelines_config, self.nodes_config)
        self._validator.validate_pipeline_dependency_graph(self.pipelines_config)
        return {
            name: self._generate_pipeline_config(name, contents)
            for name, contents in self.pipelines_config.items()
        }

    def _generate_pipeline_config(self, name: str, contents: Dict[str, Any]) -> Dict[str, Any]:
        """Generate complete configuration for a specific pipeline."""
        return {
            "name": name,
            "nodes": [
                {**(self.nodes_config[node_name] or {}), "name": node_name}
                for node_name in contents.get("nodes", [])
            ],
            "inputs": contents.get("inputs", []),
            "outputs": contents.get("outputs", []),
            "type": contents.get("type", "batch"),
            "spark_config": contents.get("spark_config", {}),
            "requires_dates": contents.get("requires_dates", True),
        }

    def get_pipeline(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a specific pipeline configuration by name."""
        return self.pipelines.get(name)

    def list_pipeline_names(self) -> List[str]:
        """Get a list of all pipeline names."""
        return list(self.pipelines.keys())

    def get_pipelines_by_type(self, pipeline_type: str) -> Dict[str, Dict[str, Any]]:
        """Return pipeline raw configs filtered by type.

        Filters pipelines_config by the 'type' field, defaulting to 'batch'
        when the key is absent (consistent with PipelineSchema default).
        """
        return {
            name: cfg
            for name, cfg in self.pipelines_config.items()
            if cfg.get("type", "batch") == pipeline_type
        }


class MLConfigMixin:
    """ML configuration accessors — mixed into Context via inheritance."""

    global_settings: Dict[str, Any]
    pipelines_config: Dict[str, Any]
    nodes_config: Dict[str, Any]
    ml_info: Dict[str, Any]
    layer: str
    _config_loader: Any

    def _load_ml_info(self, ml_info_source: Optional[Union[str, Dict[str, Any], Path]]) -> None:
        source = (
            ml_info_source if ml_info_source is not None else self.global_settings.get("ml_info")
        )

        if isinstance(source, dict):
            data = source
        elif isinstance(source, (str, Path)):
            data = self._config_loader.load_config(Path(source))
            if not isinstance(data, dict):
                raise ConfigValidationError(
                    f"ml_info must be a dict (or path to a dict), got {type(data).__name__}"
                )
        else:
            data = {}

        self._process_ml_info(data)
        self.ml_info: Dict[str, Any] = data

    def _process_ml_info(self, ml_info_data: Dict[str, Any]) -> None:
        try:
            VariableInterpolator.interpolate_structure(ml_info_data, self.global_settings)
        except ConfigLoadError as exc:
            logger.debug("ML info interpolation skipped: {}", exc)
        except Exception as exc:
            logger.debug("ML info interpolation skipped (unexpected): {}", exc)

        ml_info_data["hyperparams"] = {
            **self.default_hyperparams,
            **(ml_info_data.get("hyperparams") or {}),
        }

        if not ml_info_data.get("model_version") and self.default_model_version is not None:
            ml_info_data["model_version"] = self.default_model_version
            logger.debug(f"Applied default model_version: {self.default_model_version}")

        # Store hyperparams_config_path from global_settings for later resolution
        hp_path = self.global_settings.get("hyperparams_config_path")
        if hp_path:
            ml_info_data.setdefault("hyperparams_config_path", str(hp_path))

    def get_pipeline_ml_config(self, pipeline_name: str) -> Dict[str, Any]:
        """Get ML-specific configuration for a pipeline (base implementation)."""
        pipeline = self.pipelines_config.get(pipeline_name, {})
        return {
            "model_version": pipeline.get("model_version", self.default_model_version),
            "hyperparams": self._merge_hyperparams(pipeline.get("hyperparams", {})),
            "description": pipeline.get("description", ""),
        }

    def get_pipeline_ml_info(self, pipeline_name: str) -> Dict[str, Any]:
        """Combine base ml_info with pipeline-specific ML config."""
        base = dict(self.ml_info or {})
        pconf = self.get_pipeline_ml_config(pipeline_name)

        merged_hyper = {**(base.get("hyperparams") or {}), **(pconf.get("hyperparams") or {})}

        model_version = (
            pconf.get("model_version") or base.get("model_version") or self.default_model_version
        )

        project_name = self.global_settings.get("project_name", "")

        base_model_name = base.get("model_name") or ""
        pipeline_model_name = pconf.get("model_name") or ""
        model_name = pipeline_model_name or base_model_name or pipeline_name

        # Resolve hyperparams_config
        hyperparams_config = self._resolve_hyperparams_config(pipeline_name)

        return {
            **base,
            "project_name": project_name,
            "model_name": model_name,
            "model_version": model_version,
            "hyperparams": merged_hyper,
            "hyperparams_config": hyperparams_config,
            "pipeline_config": pconf,
        }

    def _resolve_hyperparams_config(self, pipeline_name: str) -> Optional[HyperparamConfig]:
        """Resolve the HyperparamConfig for a pipeline.

        Priority:
        1. Pipeline-level ``hyperparams_config`` (key name or {path, key} dict)
        2. ``hyperparams_config_path`` from global_settings + ``ml_info.hyperparams_config`` key
        3. No config → None
        """
        pipeline = self.pipelines_config.get(pipeline_name, {}) or {}
        hp_path = self.global_settings.get("hyperparams_config_path")
        hp_info = (self.ml_info or {}).get("hyperparams_config")

        # Check pipeline-level override first
        pipeline_hp = pipeline.get("hyperparams_config")
        if pipeline_hp is not None:
            if isinstance(pipeline_hp, str):
                # Key name in the YAML file
                if hp_path:
                    return load_hyperparams_config(str(hp_path), pipeline_key=pipeline_hp)
            elif isinstance(pipeline_hp, dict):
                # Full override: {path, key}
                p = pipeline_hp.get("path", hp_path)
                k = pipeline_hp.get("key")
                if p and k:
                    return load_hyperparams_config(str(p), pipeline_key=k)
            return None

        # Fall back to ml_info inline config (key in the same YAML as ml_info)
        if isinstance(hp_info, str) and hp_path:
            return load_hyperparams_config(str(hp_path), pipeline_key=hp_info)

        # Fall back to hyperparams_config_path without a key (single-pipeline file)
        if hp_path:
            return load_hyperparams_config(str(hp_path))

        return None

    @property
    def default_model_version(self) -> Optional[str]:
        return (self.global_settings or {}).get("default_model_version")

    def get_node_ml_config(self, node_name: str) -> Dict[str, Any]:
        """Get ML-specific configuration for a node."""
        node = self.nodes_config.get(node_name, {})
        return {
            "hyperparams": node.get("hyperparams", {}),
            "metrics": node.get("metrics", []),
            "description": node.get("description", ""),
        }

    def _merge_hyperparams(self, pipeline_hyperparams: Dict[str, Any]) -> Dict[str, Any]:
        """Merge default hyperparams with pipeline-specific ones."""
        merged = self.default_hyperparams.copy()
        if pipeline_hyperparams:
            merged.update(pipeline_hyperparams)
        return merged

    @cached_property
    def default_hyperparams(self) -> Dict[str, Any]:
        return dict((self.global_settings or {}).get("default_hyperparams", {}) or {})

    @property
    def is_ml_layer(self) -> bool:
        """Check if this is an ML layer."""
        return self.layer == "ml"


class Context(MLConfigMixin):
    """Context for managing configuration-based pipelines with ML/Streaming support."""

    REQUIRED_GLOBAL_SETTINGS = ["input_path", "output_path", "mode"]

    def __init__(
        self,
        global_settings: Union[str, Dict, Path],
        pipelines_config: Union[str, Dict, Path],
        nodes_config: Union[str, Dict, Path],
        input_config: Union[str, Dict, Path],
        output_config: Union[str, Dict, Path],
        *,
        ml_info: Optional[Union[str, Dict[str, Any], Path]] = None,
        spark_session: Optional[Any] = None,
        validate: bool = True,
        env: Optional[str] = None,
        allow_python_config: bool = True,
    ):
        """Initialize the context with configuration sources."""
        self.allow_python_config = allow_python_config
        self._config_loader = ConfigLoaderFactory(allow_python=allow_python_config)
        self._validator = ConfigValidator()
        self._interpolator = VariableInterpolator()
        self._validate_with_pydantic = validate
        self.env: Optional[str] = env

        logger.debug("Normalizing configuration sources")
        prepared_sources = self._prepare_sources(
            global_settings=global_settings,
            pipelines_config=pipelines_config,
            nodes_config=nodes_config,
            input_config=input_config,
            output_config=output_config,
        )

        self._load_configurations(**prepared_sources)
        logger.debug("Configurations loaded successfully")

        self._apply_environment_overrides()

        self._load_ml_info(ml_info)
        self._process_configurations()

        self.format_policy = FormatPolicy(self.global_settings.get("format_policy", {}))
        # Spark is created lazily (see the `spark` cached_property below) — an explicit
        # override still wins outright and skips the factory entirely.
        if spark_session is not None:
            self.spark = spark_session
        self._pipeline_manager = PipelineManager(self.pipelines_config, self.nodes_config)
        self.quality_output_paths: List[QualityOutputPath] = []

    @cached_property
    def spark(self):
        """Lazily create (or reuse, via SparkSessionManager's cache) the Spark
        session for this context's execution_mode.

        Not created until first genuine access — commands/pipelines that never
        touch Spark-backed I/O or ML nodes (e.g. `list-pipelines`, `config
        validate`, quality-check-only pipelines) pay zero JVM/session cost.
        """
        return SparkSessionFactory.get_session(
            self.execution_mode, ml_config=self._get_spark_ml_config()
        )

    def has_spark_session(self) -> bool:
        """True if `.spark` has already been materialized for this context.

        Does NOT trigger creation itself — safe to call from cleanup or
        context-reuse paths that must not force a session into existence just
        to check whether one exists.
        """
        return "spark" in vars(self)

    @classmethod
    def _from_processed(
        cls,
        global_settings: Dict[str, Any],
        pipelines_config: Dict[str, Any],
        nodes_config: Dict[str, Any],
        input_config: Dict[str, Any],
        output_config: Dict[str, Any],
        ml_info: Optional[Dict[str, Any]] = None,
        spark_session: Optional[Any] = None,
        env: Optional[str] = None,
        allow_python_config: bool = True,
    ) -> "Context":
        """Create a Context (or subclass) from already-loaded and processed config dicts."""
        obj = cls.__new__(cls)
        obj.allow_python_config = allow_python_config
        obj._config_loader = ConfigLoaderFactory(allow_python=allow_python_config)
        obj._validator = ConfigValidator()
        obj._interpolator = VariableInterpolator()
        obj._validate_with_pydantic = False
        obj.env = env
        obj.global_settings = global_settings
        obj.pipelines_config = pipelines_config
        obj.nodes_config = nodes_config
        obj.input_config = input_config
        obj.output_config = output_config
        obj.execution_mode = global_settings.get("mode", "local")
        obj.input_path = global_settings.get("input_path")
        obj.output_path = global_settings.get("output_path")
        obj.ml_info = ml_info if isinstance(ml_info, dict) else {}
        obj.layer = global_settings.get("layer", "").lower()
        obj.format_policy = FormatPolicy(global_settings.get("format_policy", {}))
        # Same laziness as __init__: an explicit override wins outright, otherwise
        # the `spark` cached_property resolves it on first real access.
        if spark_session is not None:
            obj.spark = spark_session
        obj._pipeline_manager = PipelineManager(obj.pipelines_config, obj.nodes_config)
        obj.quality_output_paths = []
        logger.debug("Context created via _from_processed (fast path)")
        return obj

    @staticmethod
    def _prepare_sources(
        global_settings: Union[str, Dict, Path],
        pipelines_config: Union[str, Dict, Path],
        nodes_config: Union[str, Dict, Path],
        input_config: Union[str, Dict, Path],
        output_config: Union[str, Dict, Path],
    ) -> Dict[str, Union[str, Dict, Path]]:
        """Normalize all configuration sources to Path or dict."""

        def _norm(s: Union[str, Dict, Path]) -> Union[str, Dict, Path]:
            return Path(s) if isinstance(s, str) and not s.strip().startswith("{") else s

        return {
            "global_settings": _norm(global_settings),
            "pipelines_config": _norm(pipelines_config),
            "nodes_config": _norm(nodes_config),
            "input_config": _norm(input_config),
            "output_config": _norm(output_config),
        }

    def _load_configurations(
        self,
        global_settings: Union[str, Dict, Path],
        pipelines_config: Union[str, Dict, Path],
        nodes_config: Union[str, Dict, Path],
        input_config: Union[str, Dict, Path],
        output_config: Union[str, Dict, Path],
    ) -> None:
        """Load all configuration sources and validate global settings."""
        named_sources = {
            "global_settings": (global_settings, "global settings"),
            "pipelines_config": (pipelines_config, "pipelines config"),
            "nodes_config": (nodes_config, "nodes config"),
            "input_config": (input_config, "input config"),
            "output_config": (output_config, "output config"),
        }

        file_keys = [k for k, (src, _) in named_sources.items() if isinstance(src, (str, Path))]

        if file_keys:
            loaded: Dict[str, Any] = {}
            with ThreadPoolExecutor(max_workers=len(file_keys)) as executor:
                futures = {
                    executor.submit(
                        self._load_and_validate_config,
                        named_sources[k][0],
                        named_sources[k][1],
                    ): k
                    for k in file_keys
                }
                for future in as_completed(futures):
                    key = futures[future]
                    loaded[key] = future.result()
            resolved = {k: loaded[k] if k in loaded else named_sources[k][0] for k in named_sources}
        else:
            resolved = {
                k: self._load_and_validate_config(src, label)
                for k, (src, label) in named_sources.items()
            }

        self.global_settings = resolved["global_settings"]
        self._validator.validate_required_keys(
            self.global_settings, self.REQUIRED_GLOBAL_SETTINGS, "global settings"
        )
        # Aligned with GlobalSettingsSchema's default (mode: local). "mode" is a
        # required key, so this fallback only matters for unvalidated contexts.
        self.execution_mode = self.global_settings.get("mode", "local")
        self.input_path = self.global_settings.get("input_path")
        self.output_path = self.global_settings.get("output_path")
        self.pipelines_config = resolved["pipelines_config"]
        self.nodes_config = resolved["nodes_config"]
        self.input_config = resolved["input_config"]
        self.output_config = resolved["output_config"]

        if self._validate_with_pydantic:
            self._validate_all_configs_with_pydantic()

    def _validate_all_configs_with_pydantic(self) -> None:
        """Validate all loaded configurations using Pydantic schemas.

        Raises:
            ConfigValidationError: If any configuration doesn't match the schema
        """
        try:
            logger.debug("Validating configurations with Pydantic schemas")

            validated = ConfigSchema(
                global_settings=self.global_settings,
                pipelines_config=self.pipelines_config,
                nodes_config=self.nodes_config,
                input_config=self.input_config,
                output_config=self.output_config,
            )

            dicts = validated.to_dicts()

            self.global_settings = dicts["global_settings"]
            self.pipelines_config = dicts["pipelines_config"]
            self.nodes_config = dicts["nodes_config"]
            self.input_config = dicts["input_config"]
            self.output_config = dicts["output_config"]

            logger.debug("All configurations validated successfully with Pydantic")

        except Exception as e:
            raise ConfigValidationError(f"Configuration validation failed: {str(e)}") from e

    def _apply_environment_overrides(self) -> None:
        """Deep-merge inline per-environment overrides from ``global_settings``.

        A project can keep a **single** ``global_settings`` file that carries an
        ``environments`` block with minimal per-environment diffs::

            max_parallel_nodes: 4
            mlops_enabled: true
            environments:
              dev:     {max_parallel_nodes: 1, mlops_enabled: false, log_level: DEBUG}
              sandbox: {max_parallel_nodes: 2}
              prod:    {mlops_required: true}

        When the context is built for ``--env dev`` the ``dev`` overrides are
        deep-merged over the base settings, ``environment`` is set to the
        *normalized* active env (so ``${environment}`` interpolation and path
        namespacing are correct), and the ``environments`` block is stripped so
        it never leaks into runtime settings.

        The active env is normalized through the same
        :mod:`ducta.settings.environments` rules the canonical ``env_config`` root
        uses (``production`` -> ``prod``, ``development`` -> ``dev``,
        ``test``/``testing`` -> ``sandbox``), so ``--env`` behaves identically
        regardless of which configuration form loaded this Context. A
        ``sandbox_<developer>`` env falls back to the generic ``sandbox`` block
        when no per-developer entry exists, via :func:`get_base_environment`.

        Backward compatible: no ``environments`` block → only the ``environment``
        stamp is applied, exactly as before.
        """
        from ducta.setting.environments import get_base_environment, normalize_environment

        raw_active = self.env or self.global_settings.get("environment")
        active = normalize_environment(raw_active) if raw_active else raw_active
        env_overrides = self.global_settings.pop("environments", None)

        if isinstance(env_overrides, dict) and active:
            # Resolve the override for the active env, with sandbox_<dev> falling
            # back to the generic "sandbox" block.
            candidates = [active]
            base_env = get_base_environment(active)
            if base_env != active:
                candidates.append(base_env)
            overrides = next(
                (env_overrides[c] for c in candidates if isinstance(env_overrides.get(c), dict)),
                None,
            )
            if overrides:
                self.global_settings = _deep_merge_dicts(self.global_settings, overrides)
                logger.info(
                    "Applied '{}' environment overrides ({} key(s))", active, len(overrides)
                )
            elif env_overrides and active != "base":
                # A non-empty environments: block exists, the active env isn't
                # "base" (which legitimately has no override), and nothing
                # matched — most likely a typo in --env or in the block's keys.
                logger.warning(
                    "No '{}' override found in the environments: block (declared: {}). "
                    "Running with base settings only — check for a typo in --env or "
                    "in the environments: keys.",
                    active,
                    ", ".join(sorted(env_overrides.keys())),
                )

        if active:
            self.global_settings["environment"] = active

    def _load_and_validate_config(
        self, source: Union[str, Dict], config_name: str
    ) -> Dict[str, Any]:
        """Load configuration from source with validation."""
        try:
            config = self._config_loader.load_config(source)
            self._validator.validate_type(config, dict, config_name)
            return config
        except (ConfigLoadError, ConfigValidationError):
            raise
        except Exception as e:
            raise ConfigLoadError(f"Unexpected error loading {config_name}: {str(e)}") from e

    def _process_configurations(self) -> None:
        """Process and prepare configurations after loading."""
        self.layer = self.global_settings.get("layer", "").lower()

        VariableInterpolator.interpolate_structure(self.input_config, self.global_settings)
        VariableInterpolator.interpolate_structure(self.output_config, self.global_settings)
        self._interpolate_input_paths()

    def _get_spark_ml_config(self) -> Dict[str, Any]:
        """Extract Spark ML configuration from global settings."""
        return self.global_settings.get("spark_config", {})

    def _interpolate_input_paths(self) -> None:
        """Interpolate variables in input/output data paths.

        Also covers streaming nodes' *inline* I/O: a node can declare its
        source/sink directly under ``[node.input]``/``[node.output]``/
        ``[node.streaming]`` (``path``, ``checkpoint_location``) instead of
        referencing a name in the input/output catalog — those keys live in
        ``nodes_config``, which the catalog-only interpolation below never
        touches, so without this a streaming project's data and checkpoint
        locations can't vary per ``--env`` (they'd collide across
        dev/sandbox/prod). See :meth:`VariableInterpolator.interpolate_config_paths`.
        """
        variables = {
            "input_path": self.input_path,
            "output_path": self.output_path,
            "environment": self.global_settings.get("environment", ""),
        }
        self._interpolator.interpolate_config_paths(self.input_config, variables)
        self._interpolator.interpolate_config_paths(self.output_config, variables)
        self._interpolator.interpolate_config_paths(
            self.nodes_config, variables, keys=frozenset({"path", "checkpoint_location"})
        )

    @property
    def pipelines(self) -> Dict[str, Dict[str, Any]]:
        """Return all loaded and validated pipeline configurations (expanded nodes)."""
        return self._pipeline_manager.pipelines

    def get_pipeline(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a specific pipeline configuration by name."""
        return self._pipeline_manager.get_pipeline(name)

    def list_pipeline_names(self) -> List[str]:
        """Get a list of all pipeline names."""
        return self._pipeline_manager.list_pipeline_names()

    def get_pipelines_by_type(self, pipeline_type: str) -> Dict[str, Dict[str, Any]]:
        """Get pipeline raw configs filtered by type. Delegates to PipelineManager."""
        return self._pipeline_manager.get_pipelines_by_type(pipeline_type)

    def add_quality_output_path(self, path: QualityOutputPath) -> None:
        """Track a persisted quality report so pipeline-end aggregation can find it."""
        self.quality_output_paths.append(path)
        logger.debug(
            f"Tracked quality output: {path.report_type} for node {path.node_name} "
            f"at {path.output_path}"
        )

    def get_quality_outputs(self) -> Dict[str, List[QualityOutputPath]]:
        """Return tracked quality outputs grouped by report type."""
        outputs: Dict[str, List[QualityOutputPath]] = {}
        for path in self.quality_output_paths:
            outputs.setdefault(path.report_type, []).append(path)
        return outputs

    def get_quality_outputs_by_node(self) -> Dict[str, List[QualityOutputPath]]:
        """Return tracked quality outputs grouped by node name."""
        outputs: Dict[str, List[QualityOutputPath]] = {}
        for path in self.quality_output_paths:
            outputs.setdefault(path.node_name, []).append(path)
        return outputs

    @classmethod
    def from_json_config(
        cls,
        global_settings: Dict[str, Any],
        pipelines_config: Dict[str, Any],
        nodes_config: Dict[str, Any],
        input_config: Dict[str, Any],
        output_config: Dict[str, Any],
    ) -> "Context":
        """Create Context instance directly from JSON/dictionary configurations."""
        return cls(
            global_settings=global_settings,
            pipelines_config=pipelines_config,
            nodes_config=nodes_config,
            input_config=input_config,
            output_config=output_config,
        )


class BaseSpecializedContext(Context, ABC):
    """Abstract base class for specialized contexts (ML/Streaming)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._validator = self._create_validator()
        try:
            self._validate_configurations()
        except ConfigValidationError as e:
            logger.error(f"Configuration validation failed: {str(e)}")
            raise

    @abstractmethod
    def _create_validator(self):
        """Create context-specific validator"""
        pass

    @abstractmethod
    def _get_specialized_nodes(self) -> Dict[str, Dict[str, Any]]:
        """Get nodes compatible with this context"""
        pass

    @abstractmethod
    def _is_compatible_node(self, node_config: Dict[str, Any]) -> bool:
        """Check node compatibility"""
        pass

    @abstractmethod
    def _get_context_type_name(self) -> str:
        """Get human-readable context name"""
        pass

    def _validate_configurations(self) -> None:
        """Template method for context-specific validation"""
        self._validate_specialized_node_dependencies()

    def _validate_specialized_node_dependencies(self) -> None:
        """Validate that dependencies declared by specialized nodes actually exist."""
        specialized_nodes = self._get_specialized_nodes()
        context_type = self._get_context_type_name()

        for node_name, node_config in specialized_nodes.items():
            dependencies = node_config.get("dependencies", [])

            if not isinstance(dependencies, list):
                raise ConfigValidationError(
                    f"{context_type} node '{node_name}' dependencies must be a list"
                )

            for dep in dependencies:
                if not isinstance(dep, str):
                    raise ConfigValidationError(
                        f"{context_type} node '{node_name}' dependency must be string, got {type(dep).__name__}"
                    )

                dep_config = self.nodes_config.get(dep)

                if not dep_config:
                    raise ConfigValidationError(
                        f"{context_type} node '{node_name}' depends on missing node '{dep}'"
                    )

    def _validate_pipeline_compatibility_batch_to_specialized(
        self,
        batch_pipelines: Dict[str, Dict[str, Any]],
        specialized_pipelines: Dict[str, Dict[str, Any]],
        pipeline_type_label: str,
    ) -> None:
        """Generic pipeline compatibility validation between batch and specialized pipelines."""
        if not batch_pipelines or not specialized_pipelines:
            return

        for batch_name, batch_pipeline in batch_pipelines.items():
            for spec_name, spec_pipeline in specialized_pipelines.items():
                warnings = self._validator.validate_pipeline_compatibility(
                    batch_pipeline, spec_pipeline, self.nodes_config
                )
                for warning in warnings:
                    logger.warning(
                        f"Compatibility issue between batch pipeline '{batch_name}' "
                        f"and {pipeline_type_label} pipeline '{spec_name}': {warning}"
                    )

    @classmethod
    def from_base_context(cls, base_context: Context):
        """Create specialized context from base Context.

        Uses _from_processed to skip re-loading and re-validating the already-
        processed configs from the base context.
        """
        obj = cls._from_processed(
            global_settings=base_context.global_settings,
            pipelines_config=base_context.pipelines_config,
            nodes_config=base_context.nodes_config,
            input_config=base_context.input_config,
            output_config=base_context.output_config,
            ml_info=getattr(base_context, "ml_info", None),
            # Reuse the base context's session only if it already materialized one —
            # `getattr(base_context, "spark", None)` would otherwise force creation
            # here just to check, defeating the laziness. If the base never touched
            # Spark, the new context creates its own lazily when it needs one;
            # SparkSessionManager's mode/ml_config cache key dedupes it automatically.
            spark_session=(base_context.spark if base_context.has_spark_session() else None),
            env=base_context.env,
            allow_python_config=base_context.allow_python_config,
        )
        obj._validator = obj._create_validator()
        try:
            obj._validate_configurations()
        except ConfigValidationError as e:
            logger.error(f"Configuration validation failed: {str(e)}")
            raise
        return obj


class MLContext(BaseSpecializedContext):
    """Context for managing machine learning pipelines and configurations."""

    @cached_property
    def ml_nodes(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: node for name, node in self.nodes_config.items() if self._is_compatible_node(node)
        }

    def _create_validator(self):
        return MLValidator()

    def _get_specialized_nodes(self) -> Dict[str, Dict[str, Any]]:
        return self.ml_nodes

    def _is_compatible_node(self, node_config: Dict[str, Any]) -> bool:
        """An ML node is compatible if it declares a 'model' section."""
        return "model" in node_config

    def _get_context_type_name(self) -> str:
        return "ML"

    def _validate_configurations(self) -> None:
        super()._validate_configurations()
        strict_ml = bool(
            (self.global_settings or {}).get("validators", {}).get("ml", {}).get("strict", True)
        )
        self._validator.validate_ml_pipeline_config(
            self.ml_pipelines, self.nodes_config, strict=strict_ml
        )
        batch_pipelines = self._pipeline_manager.get_pipelines_by_type("batch")
        self._validate_pipeline_compatibility_batch_to_specialized(
            batch_pipelines, self.ml_pipelines, "ML"
        )

    @cached_property
    def ml_pipelines(self) -> Dict[str, Dict[str, Any]]:
        return self._pipeline_manager.get_pipelines_by_type("ml")


class StreamingContext(BaseSpecializedContext):
    """Context for managing streaming pipelines and configurations."""

    @cached_property
    def streaming_nodes(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: node for name, node in self.nodes_config.items() if self._is_streaming_node(node)
        }

    def _create_validator(self):
        return StreamingValidator(self.format_policy)

    def _get_specialized_nodes(self) -> Dict[str, Dict[str, Any]]:
        return self.streaming_nodes

    def _is_compatible_node(self, node_config: Dict[str, Any]) -> bool:
        return self._is_streaming_node(node_config)

    def _get_context_type_name(self) -> str:
        return "Streaming"

    def _validate_configurations(self) -> None:
        super()._validate_configurations()
        strict_streaming = bool(
            (self.global_settings or {})
            .get("validators", {})
            .get("streaming", {})
            .get("strict", True)
        )
        for pipeline_name, pipeline_config in self.streaming_pipelines.items():
            pipeline_with_name = {**pipeline_config, "name": pipeline_name}
            self._validator.validate_streaming_pipeline_config(
                pipeline_with_name, strict=strict_streaming
            )
            self._validator.validate_streaming_pipeline_with_nodes(
                pipeline_with_name, self.nodes_config, strict=strict_streaming
            )

    @cached_property
    def streaming_pipelines(self) -> Dict[str, Dict[str, Any]]:
        return self._pipeline_manager.get_pipelines_by_type("streaming")

    def _is_streaming_node(self, node_config: Dict[str, Any]) -> bool:
        input_conf = node_config.get("input", {})
        output_conf = node_config.get("output", {})

        input_format = input_conf.get("format", "") if isinstance(input_conf, dict) else ""
        output_format = output_conf.get("format", "") if isinstance(output_conf, dict) else ""

        return self._validator.policy.is_supported_input(
            input_format
        ) or self._validator.policy.is_supported_output(output_format)


class HybridContext(Context):
    """Combined context for hybrid streaming/ML pipelines."""

    def __init__(self, base_context: Context):
        self._config_loader = base_context._config_loader
        self._validator = base_context._validator
        self._interpolator = base_context._interpolator
        self._validate_with_pydantic = base_context._validate_with_pydantic
        self.env = base_context.env
        self.global_settings = base_context.global_settings
        self.execution_mode = base_context.execution_mode
        self.input_path = base_context.input_path
        self.output_path = base_context.output_path
        self.pipelines_config = base_context.pipelines_config
        self.nodes_config = base_context.nodes_config
        self.input_config = base_context.input_config
        self.output_config = base_context.output_config
        self.ml_info = base_context.ml_info if hasattr(base_context, "ml_info") else {}
        self.layer = base_context.layer if hasattr(base_context, "layer") else ""
        self.format_policy = base_context.format_policy
        self._pipeline_manager = base_context._pipeline_manager
        self.quality_output_paths = list(base_context.quality_output_paths)
        self._config_file_path = getattr(base_context, "_config_file_path", None)
        self.config_paths = getattr(base_context, "config_paths", {})
        if base_context.has_spark_session():
            self.spark = base_context.spark

        self.base_context = base_context

        self._streaming_ctx = StreamingContext.from_base_context(self)
        self._ml_ctx = MLContext.from_base_context(self)

        self._validate_hybrid_config()

    def _validate_hybrid_config(self):
        """Enhanced cross-validation for hybrid pipelines"""
        HybridValidator.validate_context(self, self._streaming_ctx, self._ml_ctx)


class ContextFactory:
    """Factory for creating specialized contexts with priority handling."""

    @staticmethod
    def create_context(base_context: Context) -> Context:
        """Create specialized context based on pipeline configurations."""
        has_streaming = bool(base_context.get_pipelines_by_type("streaming"))
        has_ml = bool(base_context.get_pipelines_by_type("ml"))
        has_hybrid = bool(base_context.get_pipelines_by_type("hybrid"))

        if has_hybrid or (has_streaming and has_ml):
            return HybridContext(base_context)
        elif has_streaming:
            return StreamingContext.from_base_context(base_context)
        elif has_ml:
            return MLContext.from_base_context(base_context)

        return base_context
