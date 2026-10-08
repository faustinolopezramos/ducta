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

import re
from typing import Any, Dict, List

from loguru import logger  # type: ignore

_IO_TOKEN_SPLIT = re.compile(r"[._\-/]+")


class MLOpsAutoConfigurator:
    """Auto-configures MLOps based on context and node patterns."""

    ML_NODE_PATTERNS = [
        "train",
        "model",
        "predict",
        "evaluate",
        "hyperparameter",
        "feature_engineering",
        "feature_selection",
        "cross_validation",
        "grid_search",
        "fit",
        "score",
        "experiment",
    ]

    ML_FUNCTION_PATTERNS = [
        "sklearn",
        "xgboost",
        "lightgbm",
        "tensorflow",
        "pytorch",
        "keras",
        "train_model",
        "fit_model",
        "build_model",
        "tune_model",
        "cross_validate",
        "grid_search",
    ]

    ML_IO_PATTERNS = ["model", "weights", "checkpoint", "hyperparams"]

    @staticmethod
    def _iter_io_keys(raw: Any) -> List[str]:
        """Normalize an ``input``/``output`` declaration to a list of dataset keys."""
        if raw is None:
            return []
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, dict):
            return [str(v) for v in raw.values()]
        if isinstance(raw, (list, tuple, set)):
            return [str(item) for item in raw]
        return [str(raw)]

    @staticmethod
    def resolve_ml_stage(node_config: Dict[str, Any]) -> str:
        """Read a node's ML lifecycle stage, accepting both spellings in the wild."""
        if not isinstance(node_config, dict):
            return ""
        # A validated config holds the MLStage enum, whose str() is "MLStage.TRAINING";
        # the value ("training") is what every caller compares against.
        flat = node_config.get("ml_stage")
        if flat:
            return str(getattr(flat, "value", flat))
        nested = node_config.get("ml")
        if isinstance(nested, dict) and nested.get("stage"):
            stage = nested["stage"]
            return str(getattr(stage, "value", stage))
        return ""

    @classmethod
    def get_logging_strategy(cls, ml_stage: str) -> Dict[str, bool]:
        """Return logging strategies based on ml_stage."""
        stage = (ml_stage or "").lower()
        if "feature" in stage or "data" in stage:
            return {"log_metrics": False, "log_schema": True, "log_artifacts": False}
        elif "train" in stage or "eval" in stage or "test" in stage:
            return {"log_metrics": True, "log_schema": False, "log_artifacts": True}
        else:
            return {"log_metrics": True, "log_schema": True, "log_artifacts": True}

    @classmethod
    def should_enable_mlops(cls, node_config: Dict[str, Any], node_name: str = "") -> bool:
        """
        Detect if a node needs MLOps automatically.
        """
        if cls.resolve_ml_stage(node_config):
            return True

        if "ml" in node_config:
            return True

        if node_config.get("mlops_enabled") is False:
            return False

        name = node_name or node_config.get("name", "")

        if any(pattern in name.lower() for pattern in cls.ML_NODE_PATTERNS):
            logger.debug(f"MLOps auto-enabled for node '{name}' (pattern match in name)")
            return True

        function_cfg = node_config.get("function", "")
        function = function_cfg.lower() if isinstance(function_cfg, str) else ""
        if any(pattern in function for pattern in cls.ML_FUNCTION_PATTERNS):
            logger.debug(f"MLOps auto-enabled for node '{name}' (pattern match in function)")
            return True

        if "hyperparams" in node_config:
            logger.debug(f"MLOps auto-enabled for node '{name}' (has hyperparams)")
            return True

        if "metrics" in node_config:
            logger.debug(f"MLOps auto-enabled for node '{name}' (has metrics)")
            return True

        for io_item in [
            *cls._iter_io_keys(node_config.get("input")),
            *cls._iter_io_keys(node_config.get("output")),
        ]:
            io_str = str(io_item).lower()
            tokens = set(_IO_TOKEN_SPLIT.split(io_str))
            if tokens & set(cls.ML_IO_PATTERNS):
                logger.debug(f"MLOps auto-enabled for node '{name}' (ML pattern in I/O: {io_str})")
                return True

        return False

    @classmethod
    def detect_pipeline_ml_nodes(cls, nodes_config: Dict[str, Dict[str, Any]]) -> List[str]:
        """
        Detect which nodes in a pipeline need MLOps.
        """
        ml_nodes = []
        for node_name, node_config in nodes_config.items():
            if cls.should_enable_mlops(node_config, node_name=node_name):
                ml_nodes.append(node_name)

        return ml_nodes

    @classmethod
    def should_init_mlops_for_pipeline(
        cls, nodes_config: Dict[str, Dict[str, Any]], global_config: Dict[str, Any]
    ) -> bool:
        """Whether this pipeline's nodes warrant experiment tracking.

        ``nodes_config`` must hold **the nodes of the pipeline being run**, not
        every node in the project. Handed the whole project, one ML node
        anywhere turns tracking on for every batch pipeline that shares the
        configuration.

        An explicit setting always wins over detection. Both spellings are
        accepted, and the nested one wins, matching
        ``CoreSettings._resolve_mlops_enabled`` — this used to read only
        ``mlops.enabled``, so the flat ``mlops_enabled`` that
        ``GlobalConfigSchema`` documents did nothing here.
        """
        mlops_section = global_config.get("mlops") or {}
        explicit = mlops_section.get("enabled")
        if explicit is None:
            explicit = global_config.get("mlops_enabled")

        if explicit is not None:
            from ducta.core.settings import coerce_bool

            enabled = coerce_bool("mlops_enabled", explicit, default=True)
            logger.info("MLOps {} by global config", "enabled" if enabled else "disabled")
            return enabled

        ml_nodes = cls.detect_pipeline_ml_nodes(nodes_config)

        if ml_nodes:
            logger.info(f"MLOps auto-enabled for pipeline (ML nodes detected: {ml_nodes})")
            return True

        logger.debug("MLOps not needed for this pipeline (no ML nodes detected)")
        return False
