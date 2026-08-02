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

    # Node name patterns that indicate ML workload
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

    # Function name patterns that indicate ML libraries
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

    # ML-related input/output patterns. Matched as whole tokens (see
    # should_enable_mlops), not substrings — "metrics" was deliberately
    # dropped: it's too generic a term for ordinary BI/analytics dataset
    # names ("sales_metrics_daily") to gate MLOps auto-detection on, unlike
    # "model"/"weights"/"checkpoint"/"hyperparams" which are specific enough
    # to rarely appear in non-ML datasets.
    ML_IO_PATTERNS = ["model", "weights", "checkpoint", "hyperparams"]

    @classmethod
    def get_logging_strategy(cls, ml_stage: str) -> Dict[str, bool]:
        """Return logging strategies based on ml_stage."""
        stage = (ml_stage or "").lower()
        if "feature" in stage or "data" in stage:
            return {"log_metrics": False, "log_schema": True, "log_artifacts": False}
        elif "train" in stage or "eval" in stage or "test" in stage:
            return {"log_metrics": True, "log_schema": False, "log_artifacts": True}
        else:
            # Default generic strategy
            return {"log_metrics": True, "log_schema": True, "log_artifacts": True}

    @classmethod
    def should_enable_mlops(cls, node_config: Dict[str, Any], node_name: str = "") -> bool:
        """
        Detect if a node needs MLOps automatically.
        """
        # Explicit ML configuration
        if "ml" in node_config:
            return True

        # Explicit opt-out
        if node_config.get("mlops_enabled") is False:
            return False

        name = node_name or node_config.get("name", "")

        # Check node name
        if any(pattern in name.lower() for pattern in cls.ML_NODE_PATTERNS):
            logger.debug(f"MLOps auto-enabled for node '{name}' (pattern match in name)")
            return True

        # Check function name.
        # `function` may be a string (legacy) or a dict (streaming transform: {key, params}).
        # A dict signals a registered streaming transform, never an ML function, so skip ML matching.
        function_cfg = node_config.get("function", "")
        function = function_cfg.lower() if isinstance(function_cfg, str) else ""
        if any(pattern in function for pattern in cls.ML_FUNCTION_PATTERNS):
            logger.debug(f"MLOps auto-enabled for node '{name}' (pattern match in function)")
            return True

        # Check for ML-related hyperparameters
        if "hyperparams" in node_config:
            logger.debug(f"MLOps auto-enabled for node '{name}' (has hyperparams)")
            return True

        # Check for ML-related metrics
        if "metrics" in node_config:
            logger.debug(f"MLOps auto-enabled for node '{name}' (has metrics)")
            return True

        # Check input/output patterns — whole-token match (split on ./_/-//),
        # not substring: a plain `pattern in io_str` check would false-positive
        # on e.g. "underscore" containing "score", or an ordinary analytics
        # dataset like "sales_metrics_daily" containing "metrics" as a
        # substring of an unrelated compound name.
        for io_item in [*node_config.get("input", []), *node_config.get("output", [])]:
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
        cls, nodes_config: Dict[str, Dict[str, Any]], global_settings: Dict[str, Any]
    ) -> bool:
        """
        Determine if MLOps should be initialized for a pipeline.
        """
        # Check global override
        mlops_global = global_settings.get("mlops", {})

        # Explicit disable
        if mlops_global.get("enabled") is False:
            logger.info("MLOps disabled by global settings")
            return False

        # Explicit enable
        if mlops_global.get("enabled") is True:
            logger.info("MLOps enabled by global settings")
            return True

        # Auto-detect: check if any node needs MLOps
        ml_nodes = cls.detect_pipeline_ml_nodes(nodes_config)

        if ml_nodes:
            logger.info(f"MLOps auto-enabled for pipeline (ML nodes detected: {ml_nodes})")
            return True

        logger.debug("MLOps not needed for this pipeline (no ML nodes detected)")
        return False
