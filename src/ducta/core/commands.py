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

import hashlib
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime
from functools import lru_cache
from inspect import Parameter, signature
from typing import Any, Callable, Dict, List, Optional, Protocol

from loguru import logger  # type: ignore


@lru_cache(maxsize=256)
def _accepts_ml_context(func: Callable) -> bool:
    """Whether ``func`` accepts an ``ml_context`` kwarg (explicit or via **kwargs).

    Cached: the result is fixed per function object, so introspecting it once per
    function instead of on every node execution avoids repeated signature parsing.
    """
    params = signature(func).parameters
    return "ml_context" in params or any(p.kind == Parameter.VAR_KEYWORD for p in params.values())


DEFAULT_VECTORIZED_MAX_ROWS = 5_000_000


def _guarded_to_pandas(dfs: List[Any], node_name: str, max_rows: Optional[int]) -> List[Any]:
    """Collect Spark DataFrames to pandas for vectorized execution, with an OOM guard."""
    converted: List[Any] = []
    for df in dfs:
        if not hasattr(df, "toPandas"):
            converted.append(df)
            continue
        if max_rows and max_rows > 0:
            try:
                overflow = df.limit(max_rows + 1).count() > max_rows
            except Exception as e:
                logger.debug("Vectorized row-count guard skipped for '{}': {}", node_name, e)
                overflow = False
            if overflow:
                raise ValueError(
                    f"Vectorized (toPandas) execution for node '{node_name}' would collect more "
                    f"than {max_rows} rows to the driver, risking OOM. Increase "
                    f"'execution_mode_max_rows' for this node only if the driver can hold it, "
                    f"or use a distributed transform (mapInPandas / Pandas UDFs)."
                )
        converted.append(df.toPandas())
    return converted


class NodeFunction(Protocol):
    def __call__(self, *dfs: Any, start_date: str, end_date: str) -> Any: ...


class Command(ABC):
    """Abstract base class for command pattern implementation."""

    @abstractmethod
    def execute(self) -> Any:
        """Execute the command and return the result."""
        pass


class NodeCommand(Command):
    """Command implementation for executing a specific node in a data pipeline."""

    def __init__(
        self,
        function: NodeFunction,
        input_dfs: List[Any],
        start_date: str,
        end_date: str,
        node_name: str,
        node_config: Optional[Dict[str, Any]] = None,
        input_names: Optional[List[str]] = None,
    ):
        self.function = function
        self.input_dfs = input_dfs
        self.start_date = start_date
        self.end_date = end_date
        self.node_name = node_name
        self.node_config = node_config or {}
        # When set, inputs are bound to function parameters by name (keyword)
        # instead of positionally. Aligned with ``input_dfs`` order.
        self.input_names = input_names

    def _bind_inputs(self, inputs: List[Any]) -> tuple:
        """Bind loaded inputs to the function call.

        Returns ``(args, kwargs)``. With named inputs (``input`` declared as a
        ``{param: dataset_key}`` map) DataFrames are passed by keyword, so the
        config order no longer has to match the function signature. Otherwise
        they are passed positionally, preserving the original behavior.
        """
        if self.input_names:
            if len(self.input_names) != len(inputs):
                raise ValueError(
                    f"Node '{self.node_name}': {len(self.input_names)} named inputs "
                    f"({self.input_names}) but {len(inputs)} datasets were loaded."
                )
            return (), dict(zip(self.input_names, inputs))
        return tuple(inputs), {}

    def execute(self) -> Any:
        """Execute the node function with the specified parameters."""
        logger.info(
            f"Executing node '{self.node_name}' with date range: {self.start_date} to {self.end_date}"
        )

        node_config = self.node_config
        is_vectorized = node_config.get("execution_mode") == "vectorized"

        try:
            inputs = self.input_dfs
            if is_vectorized:
                logger.debug(f"Vectorized execution mode enabled for node '{self.node_name}'")
                # Convert Spark DataFrames to Pandas using Arrow (driver-side collect).
                max_rows = node_config.get("execution_mode_max_rows", DEFAULT_VECTORIZED_MAX_ROWS)
                inputs = _guarded_to_pandas(self.input_dfs, self.node_name, max_rows)

            args, input_kwargs = self._bind_inputs(inputs)
            result = self.function(
                *args, **input_kwargs, start_date=self.start_date, end_date=self.end_date
            )

            if is_vectorized and hasattr(result, "to_dict") and not hasattr(result, "sparkSession"):
                logger.debug(
                    f"Converting vectorized result back to Spark for node '{self.node_name}'"
                )
                spark = getattr(self, "spark", None)
                if not spark:
                    # Fallback search in inputs
                    for df in self.input_dfs:
                        if hasattr(df, "sparkSession"):
                            spark = df.sparkSession
                            break
                if spark:
                    result = spark.createDataFrame(result)

            logger.debug(f"Node '{self.node_name}' executed successfully")
            return result
        except Exception as e:
            logger.error(f"Error executing node '{self.node_name}': {str(e)}")
            raise


class MLNodeCommand(NodeCommand):
    """Enhanced command implementation for executing ML nodes with advanced features."""

    def __init__(
        self,
        function: NodeFunction,
        input_dfs: List[Any],
        start_date: str,
        end_date: str,
        node_name: str,
        model_version: Optional[str],
        hyperparams: Optional[Dict[str, Any]] = None,
        hyperparams_config: Optional[Any] = None,
        node_config: Optional[Dict[str, Any]] = None,
        pipeline_config: Optional[Dict[str, Any]] = None,
        mlops_context: Optional[Any] = None,
        mlops_run_id: Optional[str] = None,
        seed: Optional[int] = None,
        split: Optional[Dict[str, Any]] = None,
        spark=None,
        input_names: Optional[List[str]] = None,
    ):
        super().__init__(
            function, input_dfs, start_date, end_date, node_name, input_names=input_names
        )

        self.model_version = model_version or "unknown"
        self.hyperparams = hyperparams or {}
        self.hyperparams_config = hyperparams_config
        self.node_config = node_config or {}
        self.pipeline_config = pipeline_config or {}
        self.mlops_context = mlops_context
        self.mlops_run_id = mlops_run_id
        self.seed = seed
        self.split = split
        self.spark = spark

        self.node_hyperparams = self.node_config.get("hyperparams", {}) or {}
        self.metrics = self.node_config.get("metrics", []) or []
        self.description = self.node_config.get("description", "") or ""

        self.merged_hyperparams = {**self.hyperparams, **self.node_hyperparams}

        self.execution_metadata: Dict[str, Any] = {
            "node_name": self.node_name,
            "model_version": self.model_version,
            "start_time": None,
            "end_time": None,
            "duration_seconds": None,
            "hyperparams": self.merged_hyperparams,
            "metrics": self.metrics,
        }

    def execute(self) -> Any:
        """Execute the ML node function with enhanced ML capabilities."""
        self.execution_metadata["start_time"] = datetime.now().isoformat()
        start_time = time.time()

        # Performance Phase 2: Handle vectorized execution mode (Zero-copy with Arrow)
        is_vectorized = self.node_config.get("execution_mode") == "vectorized"

        try:
            # NOTE: merged hyperparameters are delivered to the node through
            # ml_context["hyperparams"]. They are deliberately NOT pushed into
            # spark.conf — model hyperparameters are not Spark settings, the
            # "spark.<name>" namespace is reserved for engine configuration, and
            # a hyperparameter colliding with a static Spark conf could raise at
            # runtime. Genuine Spark overrides belong in pipeline.spark_config.

            logger.info(
                f"Executing ML node '{self.node_name}' with model version: {self.model_version}"
            )
            logger.info(f"Description: {self.description}")

            if self.merged_hyperparams:
                try:
                    hyperparams_str = json.dumps(self.merged_hyperparams, indent=2, default=str)
                except (TypeError, ValueError):
                    hyperparams_str = str(self.merged_hyperparams)
                logger.info(f"Using merged hyperparameters: {hyperparams_str}")

            if self.metrics:
                logger.info(f"Expected metrics: {', '.join(self.metrics)}")

            # Vectorization logic for inputs
            original_inputs = self.input_dfs
            if is_vectorized:
                logger.debug(f"Vectorized ML execution mode enabled for node '{self.node_name}'")
                max_rows = self.node_config.get(
                    "execution_mode_max_rows", DEFAULT_VECTORIZED_MAX_ROWS
                )
                self.input_dfs = _guarded_to_pandas(original_inputs, self.node_name, max_rows)

            result = self._execute_with_ml_context()

            # Vectorization logic for result
            if is_vectorized and hasattr(result, "to_dict") and not hasattr(result, "sparkSession"):
                logger.debug(
                    f"Converting vectorized ML result back to Spark for node '{self.node_name}'"
                )
                if self.spark:
                    result = self.spark.createDataFrame(result)

            # Restore original inputs to avoid side-effects in subsequent retries/logs
            self.input_dfs = original_inputs

            end_time = time.time()
            duration = end_time - start_time

            self.execution_metadata.update(
                {
                    "end_time": datetime.now().isoformat(),
                    "duration_seconds": round(duration, 2),
                    "status": "success",
                }
            )

            logger.success(f"ML node '{self.node_name}' executed successfully in {duration:.2f}s")

            return result

        except Exception as e:
            self.execution_metadata.update(
                {
                    "end_time": datetime.now().isoformat(),
                    "duration_seconds": round(time.time() - start_time, 2),
                    "status": "failed",
                    "error": str(e),
                }
            )
            logger.error(f"Error executing ML node '{self.node_name}': {str(e)}")
            raise

    def _derive_node_seed(self) -> Optional[int]:
        """Derive a deterministic per-node seed from the global seed.

        Stable across runs and independent of thread scheduling, unlike the
        process-global RNG state shared by concurrently executing nodes.
        """
        if self.seed is None:
            return None
        digest = hashlib.sha256(f"{self.seed}:{self.node_name}".encode()).hexdigest()
        return int(digest, 16) % (2**32)

    def _execute_with_ml_context(self) -> Any:
        """Execute function with ML-enhanced context."""
        from ducta.core.ml_context import MLNodeContext

        # MLNodeContext is a Mapping, so nodes using ml_context["split"] / .get(...)
        # keep working; the typed attributes add discoverability for new nodes.
        ml_context = MLNodeContext(
            model_version=self.model_version,
            hyperparams=self.merged_hyperparams,
            hyperparams_config=self.hyperparams_config,
            node_config=self.node_config,
            pipeline_config=self.pipeline_config,
            execution_metadata=self.execution_metadata,
            mlops_context=self.mlops_context,
            mlops_run_id=self.mlops_run_id,
            seed=self.seed,
            node_seed=self._derive_node_seed(),
            split=self.split,
            spark=self.spark,
        )

        accepts_ml_context = False
        try:
            accepts_ml_context = _accepts_ml_context(self.function)
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Could not analyze signature of node '{self.node_name}', "
                f"calling standard signature: {e}"
            )

        args, input_kwargs = self._bind_inputs(self.input_dfs)

        if accepts_ml_context:
            logger.debug(
                "Function supports ML context (explicit or **kwargs) - passing enhanced parameters"
            )
            result = self.function(
                *args,
                **input_kwargs,
                start_date=self.start_date,
                end_date=self.end_date,
                ml_context=ml_context,
            )
        else:
            logger.debug("Function does not accept ml_context - calling standard signature")
            result = self.function(
                *args,
                **input_kwargs,
                start_date=self.start_date,
                end_date=self.end_date,
            )

        if isinstance(result, dict):
            artifact_uri = result.get("artifact_uri")
            if artifact_uri:
                logger.info(
                    f"Node '{self.node_name}' registered model; returning strictly artifact_uri: {artifact_uri}"
                )
                return artifact_uri

            if "artifact_path" in result:
                logger.warning(
                    f"Node '{self.node_name}' returned 'artifact_path' without 'artifact_uri'. "
                    "The next node might expect an absolute URI from the Model Registry."
                )

        return result
