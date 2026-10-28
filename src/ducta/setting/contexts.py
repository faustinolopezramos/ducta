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

from functools import cached_property
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.check import QualityOutputPath
from ducta.gate.validators import is_safe_path_segment
from ducta.mlrun.hyperparams import HyperparamConfig, load_hyperparams_config
from ducta.setting.environments import normalize_environment
from ducta.setting.exceptions import ConfigLoadError, ConfigValidationError
from ducta.setting.interpolator import VariableInterpolator
from ducta.setting.schemas import ConfigSchema
from ducta.setting.session import SparkSessionFactory
from ducta.setting.validators import (
    ConfigValidator,
    FormatPolicy,
    PipelineValidator,
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
            "description": contents.get("description", ""),
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
        """Return pipeline raw configs filtered by type."""
        return {
            name: cfg
            for name, cfg in self.pipelines_config.items()
            if cfg.get("type", "batch") == pipeline_type
        }


class MLConfigMixin:
    """ML configuration accessors — mixed into Context via inheritance."""

    global_config: Dict[str, Any]
    pipelines_config: Dict[str, Any]
    nodes_config: Dict[str, Any]
    ml_info: Dict[str, Any]
    layer: str

    def _load_ml_info(self, ml_info_source: Optional[Dict[str, Any]]) -> None:
        source = ml_info_source if ml_info_source is not None else self.global_config.get("ml_info")

        if source is not None and not isinstance(source, dict):
            raise ConfigValidationError(f"ml_info must be a mapping, got {type(source).__name__}")
        data: Dict[str, Any] = source or {}

        self._process_ml_info(data)
        self.ml_info: Dict[str, Any] = data

    @staticmethod
    def _interpolate_ml_info(node: Any, variables: Dict[str, Any], where: str) -> None:
        """Interpolate each string of ``node`` on its own, in place.

        One value the interpolator refuses (a ``${..._TOKEN}`` reference, say) leaves
        only that value as written; the rest of ml_info still resolves.
        """
        if isinstance(node, dict):
            items: Any = list(node.items())
        elif isinstance(node, list):
            items = list(enumerate(node))
        else:
            return
        for key, item in items:
            here = f"{where}.{key}"
            if isinstance(item, str):
                try:
                    node[key] = VariableInterpolator.interpolate(item, variables)
                except ConfigLoadError as exc:
                    logger.warning("{} left uninterpolated: {}", here, exc)
            else:
                MLConfigMixin._interpolate_ml_info(item, variables, here)

    def _process_ml_info(self, ml_info_data: Dict[str, Any]) -> None:
        self._interpolate_ml_info(ml_info_data, self.global_config, "ml_info")

        ml_info_data["hyperparams"] = {
            **self.default_hyperparams,
            **(ml_info_data.get("hyperparams") or {}),
        }

        if not ml_info_data.get("model_version") and self.default_model_version is not None:
            ml_info_data["model_version"] = self.default_model_version
            logger.debug(f"Applied default model_version: {self.default_model_version}")

        # Store hyperparams_config_path from global_config for later resolution
        hp_path = self.global_config.get("hyperparams_config_path")
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

        project_name = self.global_config.get("project_name", "")

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
        """Resolve the HyperparamConfig for a pipeline."""
        pipeline = self.pipelines_config.get(pipeline_name, {}) or {}
        hp_path = self.global_config.get("hyperparams_config_path")
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

        if hp_path and pipeline.get("type") == "ml":
            # A pipeline that names no key uses a one-key file as it is; with several
            # keys it simply has no search (a pipeline that only reads runs, say).
            return load_hyperparams_config(str(hp_path), required=False)

        return None

    @property
    def default_model_version(self) -> Optional[str]:
        return (self.global_config or {}).get("default_model_version")

    def get_node_ml_config(self, node_name: str) -> Dict[str, Any]:
        """Get ML-specific configuration for a node."""
        node = self.nodes_config.get(node_name, {})
        return {
            "hyperparams": node.get("hyperparams", {}) or {},
            "metrics": node.get("metrics", []),
            "description": node.get("description", ""),
            # These two were dropped here, so a `split:` or `model_version:` written on a
            # node never reached its ml_context and the pipeline's (or none) was used.
            "split": node.get("split"),
            "model_version": node.get("model_version"),
        }

    def _merge_hyperparams(self, pipeline_hyperparams: Dict[str, Any]) -> Dict[str, Any]:
        """Merge default hyperparams with pipeline-specific ones."""
        merged = self.default_hyperparams.copy()
        if pipeline_hyperparams:
            merged.update(pipeline_hyperparams)
        return merged

    @cached_property
    def default_hyperparams(self) -> Dict[str, Any]:
        return dict((self.global_config or {}).get("default_hyperparams", {}) or {})

    @property
    def is_ml_layer(self) -> bool:
        """Check if this is an ML layer."""
        return self.layer == "ml"


class Context(MLConfigMixin):
    """Context for managing configuration-based pipelines with ML/Streaming support.

    The five documents are plain mappings, as ``compile_project`` produces them.
    """

    REQUIRED_GLOBAL_CONFIG = ["input_path", "output_path", "mode"]

    def __init__(
        self,
        global_config: Dict[str, Any],
        pipelines_config: Dict[str, Any],
        nodes_config: Dict[str, Any],
        input_config: Dict[str, Any],
        output_config: Dict[str, Any],
        *,
        ml_info: Optional[Dict[str, Any]] = None,
        spark_session: Optional[Any] = None,
        validate: bool = True,
        env: Optional[str] = None,
    ):
        """Initialize the context with its configuration documents."""
        self._validator = ConfigValidator()
        self._interpolator = VariableInterpolator()
        self._validate_with_pydantic = validate
        self.env: Optional[str] = env

        self._load_configurations(
            global_config=global_config,
            pipelines_config=pipelines_config,
            nodes_config=nodes_config,
            input_config=input_config,
            output_config=output_config,
        )
        logger.debug("Configurations loaded successfully")

        self._apply_environment()

        self._load_ml_info(ml_info)
        self._process_configurations()

        self.format_policy = FormatPolicy(self.global_config.get("format_policy", {}))
        if spark_session is not None:
            self.spark = spark_session
        self._pipeline_manager = PipelineManager(self.pipelines_config, self.nodes_config)
        self.quality_output_paths: List[QualityOutputPath] = []

    @cached_property
    def spark(self):
        """Lazily create (or reuse, via SparkSessionManager's cache) the Spark
        session for this context's execution_mode.
        """
        return SparkSessionFactory.get_session(
            self.execution_mode, ml_config=self._get_spark_ml_config()
        )

    def has_spark_session(self) -> bool:
        """True if `.spark` has already been materialized for this context."""
        return "spark" in vars(self)

    def _load_configurations(
        self,
        global_config: Dict[str, Any],
        pipelines_config: Dict[str, Any],
        nodes_config: Dict[str, Any],
        input_config: Dict[str, Any],
        output_config: Dict[str, Any],
    ) -> None:
        """Check the five documents are mappings and validate the global config."""
        for document, label in (
            (global_config, "global config"),
            (pipelines_config, "pipelines config"),
            (nodes_config, "nodes config"),
            (input_config, "input config"),
            (output_config, "output config"),
        ):
            self._validator.validate_type(document, dict, label)

        self.global_config = global_config
        self._validator.validate_required_keys(
            self.global_config, self.REQUIRED_GLOBAL_CONFIG, "global config"
        )
        self.execution_mode = self.global_config.get("mode", "local")
        self.input_path = self.global_config.get("input_path")
        self.output_path = self.global_config.get("output_path")
        self.pipelines_config = pipelines_config
        self.nodes_config = nodes_config
        self.input_config = input_config
        self.output_config = output_config

        if self._validate_with_pydantic:
            self._validate_all_configs_with_pydantic()

    def _validate_all_configs_with_pydantic(self) -> None:
        """Validate all loaded configurations using Pydantic schemas."""
        try:
            logger.debug("Validating configurations with Pydantic schemas")

            validated = ConfigSchema.model_validate(
                {
                    "global_config": self.global_config,
                    "pipelines_config": self.pipelines_config,
                    "nodes_config": self.nodes_config,
                    "input_config": self.input_config,
                    "output_config": self.output_config,
                }
            )

            dicts = validated.to_dicts()

            self.global_config = dicts["global_config"]
            self.pipelines_config = dicts["pipelines_config"]
            self.nodes_config = dicts["nodes_config"]
            self.input_config = dicts["input_config"]
            self.output_config = dicts["output_config"]

            logger.debug("All configurations validated successfully with Pydantic")

        except Exception as e:
            raise ConfigValidationError(f"Configuration validation failed: {str(e)}") from e

    def _apply_environment(self) -> None:
        """Record the active environment (``env``, or the one the config names)."""
        raw_active = self.env or self.global_config.get("environment")
        active = normalize_environment(raw_active) if raw_active else raw_active
        if active:
            if not is_safe_path_segment(active):
                raise ConfigValidationError(
                    f"Invalid environment {active!r}: it names the folders a run writes to, so "
                    "it cannot be empty, contain a path separator, ':' or '..', or hold control "
                    "characters."
                )
            self.global_config["environment"] = active

    def _process_configurations(self) -> None:
        """Process and prepare configurations after loading."""
        self.layer = self.global_config.get("layer", "").lower()

        VariableInterpolator.interpolate_structure(self.input_config, self.global_config)
        VariableInterpolator.interpolate_structure(self.output_config, self.global_config)
        self._interpolate_input_paths()

    def _get_spark_ml_config(self) -> Dict[str, Any]:
        """Extract Spark configuration from global config.

        A local session also gets Delta Lake wired in when any input or output
        of the project is ``format: delta`` — without it, a local Delta read or
        write failed with a class-not-found from Spark. ``spark_config`` keys
        always win, and Databricks sessions ship Delta already.
        """
        user = dict(self.global_config.get("spark_config", {}) or {})
        if str(self.execution_mode).lower() != "local" or not self._uses_delta():
            return user
        from ducta.setting.session import local_delta_configs

        return {**local_delta_configs(self.global_config.get("delta_package")), **user}

    def _uses_delta(self) -> bool:
        for catalog in (self.input_config, self.output_config):
            for entry in (catalog or {}).values():
                if not isinstance(entry, dict):
                    continue
                fmt = entry.get("format", "")
                if str(getattr(fmt, "value", fmt)).lower() == "delta":
                    return True
        return False

    def _interpolate_input_paths(self) -> None:
        """Interpolate variables in input/output data paths."""
        variables = {
            "input_path": self.input_path,
            "output_path": self.output_path,
            "environment": self.global_config.get("environment", ""),
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
