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

import threading
import time
from functools import lru_cache
from inspect import Parameter, Signature, signature
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple

from loguru import logger  # type: ignore

try:
    from pyspark.sql import DataFrame  # type: ignore
    from pyspark.sql.streaming import StreamingQuery  # type: ignore
except ImportError:  # PySpark not installed (e.g. pure-Python test environments)
    DataFrame = Any  # type: ignore
    StreamingQuery = Any  # type: ignore

try:
    import pyspark.sql.functions as _f  # type: ignore
except ImportError:
    _f = None  # type: ignore

from ducta.stream.checkpoints import CheckpointManager
from ducta.stream.constants import DEFAULT_STREAMING_CONFIG, StreamingOutputMode
from ducta.stream.exceptions import (
    StreamingConfigurationError,
    StreamingError,
    StreamingQueryError,
    StreamingTimeoutError,
    create_error_context,
    handle_streaming_error,
)
from ducta.stream.readers import StreamingReaderFactory
from ducta.stream.trigger_scheduler import TriggerScheduler
from ducta.stream.validators import StreamingValidator
from ducta.stream.writers import StreamingWriterFactory

DEFAULT_PROCESSING_TIME_INTERVAL = "10 seconds"


@lru_cache(maxsize=256)
def _cached_signature(func: Callable) -> Signature:
    """Cache inspect.signature results to avoid repeated introspection per batch."""
    return signature(func)


_TIMESTAMP_CASTABLE_TYPES = frozenset(
    {
        "timestamp",
        "timestamp_ntz",
        "date",
        "string",
        "long",
        "bigint",
        "int",
        "integer",
        "double",
        "float",
        "decimal",
    }
)


class TransformationRegistry:
    """
    Secure registry for streaming transformations.
    """

    # --- class-level (global) state kept for backward-compat ---
    _registry: ClassVar[Dict[str, Callable[..., DataFrame]]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        """Create an isolated registry instance with its own state."""
        self._inst_registry: Dict[str, Callable[..., DataFrame]] = {}
        self._inst_lock = threading.Lock()

    # ---- instance methods (isolated state) ----

    def register(self, key: str, func: Callable[..., DataFrame]) -> None:  # noqa: F811
        """Register a transformation function in this isolated registry instance."""
        if not key or not isinstance(key, str):
            raise ValueError("Transformation key must be a non-empty string")
        if not key.strip():
            raise ValueError("Transformation key cannot be whitespace only")
        if not callable(func):
            raise TypeError(f"Transformation must be callable, got {type(func).__name__}")
        with self._inst_lock:
            if key in self._inst_registry:
                logger.warning(f"Overwriting existing transformation: {key}")
            self._inst_registry[key] = func
            logger.debug(f"Registered transformation (instance): {key}")

    def get(self, key: str) -> Callable[..., DataFrame]:  # noqa: F811
        """Get a transformation from this isolated registry instance."""
        with self._inst_lock:
            if key not in self._inst_registry:
                available = sorted(self._inst_registry.keys())
                raise ValueError(
                    f"Transformation '{key}' not registered. Available transformations: {available}"
                )
            return self._inst_registry[key]

    def list_transformations(self) -> List[str]:  # noqa: F811
        """List all transformations in this isolated registry instance."""
        with self._inst_lock:
            return sorted(self._inst_registry.keys())

    def unregister(self, key: str) -> bool:  # noqa: F811
        """Unregister a transformation. Returns True if existed."""
        with self._inst_lock:
            if key in self._inst_registry:
                del self._inst_registry[key]
                return True
            return False

    def clear(self) -> None:  # noqa: F811
        """Clear all transformations in this isolated registry instance."""
        with self._inst_lock:
            self._inst_registry.clear()
            logger.debug("Cleared all transformations (instance)")

    # ---- classmethods (global shared state — backward-compat) ----

    @classmethod
    def class_register(cls, key: str, func: Callable[..., DataFrame]) -> None:
        """Register a transformation in the global class-level registry."""
        logger.warning(
            "TransformationRegistry.class_register() uses a process-wide shared registry "
            "that can cause state leakage between pipelines and tests. "
            "Prefer creating a TransformationRegistry() instance and calling .register() on it."
        )
        if not key or not isinstance(key, str):
            raise ValueError("Transformation key must be a non-empty string")
        if not key.strip():
            raise ValueError("Transformation key cannot be whitespace only")
        if not callable(func):
            raise TypeError(f"Transformation must be callable, got {type(func).__name__}")
        with cls._lock:
            if key in cls._registry:
                logger.warning(f"Overwriting existing transformation: {key}")
            cls._registry[key] = func
            logger.debug(f"Registered transformation (global): {key}")

    @classmethod
    def class_get(cls, key: str) -> Callable[..., DataFrame]:
        """Get a transformation from the global registry."""
        with cls._lock:
            if key not in cls._registry:
                available = sorted(cls._registry.keys())
                raise ValueError(
                    f"Transformation '{key}' not registered. Available transformations: {available}"
                )
            return cls._registry[key]

    @classmethod
    def class_list_transformations(cls) -> List[str]:
        """List all transformations in the global registry."""
        with cls._lock:
            return sorted(cls._registry.keys())

    @classmethod
    def class_unregister(cls, key: str) -> bool:
        """Unregister a transformation from the global registry. Returns True if existed."""
        with cls._lock:
            if key in cls._registry:
                del cls._registry[key]
                return True
            return False


class StreamingQueryManager:
    """
    Manages individual streaming queries with lifecycle and configuration.
    """

    def __init__(
        self,
        context,
        validator: Optional[StreamingValidator] = None,
        progress_sink: Optional[Any] = None,
    ):
        """
        Initialize the StreamingQueryManager.
        """
        self.context = context
        self.reader_factory = StreamingReaderFactory(context)
        self.writer_factory = StreamingWriterFactory(context)
        policy = getattr(context, "format_policy", None)
        self.validator = validator or StreamingValidator(policy)
        self.transformation_registry = TransformationRegistry()
        # Optional StreamingProgressSink used to make the "adaptive" trigger
        # consult historical batch durations from prior runs of a query.
        self.progress_sink = progress_sink
        # Checkpoint resolution/reservation and trigger scheduling live in their
        # own collaborators (composition, not inheritance); this class keeps only
        # query lifecycle concerns and delegates the rest.
        self.checkpoint_manager = CheckpointManager(context)
        self.trigger_scheduler = TriggerScheduler(context, self.validator, progress_sink)
        # Serializes the conf-set + query .start() window so each streaming
        # query captures its own per-query shuffle.partitions / scheduler pool
        # instead of racing with other concurrent starts on the shared session.
        self._query_start_lock = threading.Lock()

        active_env = getattr(self.context, "env", None) or getattr(
            self.context, "environment", None
        )
        if active_env:
            logger.debug(f"StreamingQueryManager initialized for environment: '{active_env}'")
        self.active_environment = active_env

        self._active_queries: Dict[str, Dict[str, Any]] = {}  # Track active queries
        self._active_queries_lock = threading.Lock()

    def _is_query_active(self, query: StreamingQuery) -> bool:
        """Check if a streaming query is currently active."""
        is_active = getattr(query, "isActive", None)
        if callable(is_active):
            try:
                return bool(is_active())
            except Exception as e:
                logger.debug(f"Error checking query active state: {e}")
                return False
        return bool(is_active) if is_active is not None else False

    def _get_query_name(self, query: StreamingQuery) -> Optional[str]:
        """Get the name of a streaming query."""
        return getattr(query, "name", getattr(query, "queryName", None))

    def _get_query_id(self, query: StreamingQuery) -> Optional[str]:
        """Get the unique identifier of a streaming query."""
        query_id = getattr(query, "id", None)
        return str(query_id) if query_id is not None else None

    @handle_streaming_error
    def create_and_start_query(
        self, node_config: Dict[str, Any], execution_id: str, pipeline_name: str
    ) -> StreamingQuery:
        """
        Create and start a streaming query from node configuration.
        """
        try:
            self.validator.validate_streaming_node_config(node_config)

            node_name = node_config.get("name", "unknown")
            logger.info(f"Creating streaming query for node '{node_name}'")

            input_df = self._load_streaming_input(node_config)
            transformed_df = self._apply_transformations(input_df, node_config)
            query, checkpoint_location = self._configure_and_start_query(
                transformed_df, node_config, execution_id, pipeline_name
            )

            query_key = f"{pipeline_name}:{execution_id}:{node_name}"
            # Move checkpoint from reserved to active_queries in a single lock acquisition
            # so the slot is never simultaneously unclaimed.
            with self._active_queries_lock:
                self._active_queries[query_key] = {
                    "query": query,
                    "node_config": node_config,
                    "start_time": time.time(),
                    "execution_id": execution_id,
                    "pipeline_name": pipeline_name,
                    "node_name": node_name,
                    "resolved_checkpoint": checkpoint_location,
                }
                self.checkpoint_manager.discard_reservation(checkpoint_location)

            qid = self._get_query_id(query)
            qname = self._get_query_name(query) or node_name
            logger.info(f"Streaming query '{qname}' started with ID: {qid}")
            return query

        except Exception as e:
            context = create_error_context(
                operation="create_and_start_query",
                component="StreamingQueryManager",
                node_name=node_config.get("name", "unknown"),
                execution_id=execution_id,
                pipeline_name=pipeline_name,
            )

            if isinstance(e, StreamingError):
                e.add_context("operation_context", context)
                raise
            else:
                raise StreamingQueryError(
                    f"Failed to create streaming query: {str(e)}",
                    context=context,
                    cause=e,
                ) from e

    def _load_streaming_input(self, node_config: Dict[str, Any]) -> DataFrame:
        """
        Load streaming input DataFrame with error handling.
        """
        try:
            input_config = node_config.get("input", {})
            if not input_config:
                raise StreamingConfigurationError(
                    "Streaming node must have input configuration",
                    config_section="input",
                )

            format_type = input_config.get("format")
            if not format_type:
                raise StreamingConfigurationError(
                    "Streaming input must specify format", config_section="input.format"
                )

            reader = self.reader_factory.get_reader(format_type)

            streaming_df = reader.read_stream(input_config)

            # streaming.watermark (documented location) takes precedence over
            # the legacy input.watermark, which is kept as a fallback.
            streaming_block = node_config.get("streaming", {}) or {}
            watermark_config = streaming_block.get("watermark") or input_config.get("watermark")
            if watermark_config:
                streaming_df = self._apply_watermark(streaming_df, watermark_config)

            return streaming_df

        except Exception as e:
            logger.error(f"Error loading streaming input: {str(e)}")
            if isinstance(e, StreamingError):
                raise
            else:
                raise StreamingError(
                    f"Failed to load streaming input: {str(e)}",
                    error_code="INPUT_LOAD_ERROR",
                    cause=e,
                ) from e

    def _apply_watermark(
        self, streaming_df: DataFrame, watermark_config: Dict[str, Any]
    ) -> DataFrame:
        """
        Apply watermark on the streaming DataFrame using provided config.
        """
        try:
            timestamp_col = watermark_config.get("column")
            delay_threshold = watermark_config.get("delay", DEFAULT_PROCESSING_TIME_INTERVAL)

            if not timestamp_col:
                raise StreamingConfigurationError(
                    "Watermark configuration must specify 'column'",
                    config_section="watermark.column",
                )

            if timestamp_col not in streaming_df.columns:
                available_cols = streaming_df.columns
                raise StreamingConfigurationError(
                    f"Watermark column '{timestamp_col}' not found in DataFrame. Available columns: {available_cols}",
                    config_section="watermark.column",
                    config_value=timestamp_col,
                )

            dtype = dict(streaming_df.dtypes).get(timestamp_col, "unknown")
            if dtype not in ("timestamp", "date"):
                # Reject types that Spark cannot cast to timestamp — fail early with a
                # clear error rather than letting the lazy Spark plan fail at query start.
                base_dtype = dtype.split("(")[0].lower()  # strip precision, e.g. "decimal(10,2)"
                if base_dtype not in _TIMESTAMP_CASTABLE_TYPES:
                    raise StreamingConfigurationError(
                        f"Watermark column '{timestamp_col}' has type '{dtype}' which cannot be cast "
                        f"to timestamp. Use a string, numeric, or temporal column.",
                        config_section="watermark.column",
                        config_value=timestamp_col,
                        context={
                            "column": timestamp_col,
                            "detected_type": dtype,
                            "castable_types": sorted(_TIMESTAMP_CASTABLE_TYPES),
                        },
                    )
                logger.warning(
                    f"Watermark column '{timestamp_col}' has type '{dtype}', casting to timestamp"
                )
                try:
                    streaming_df = streaming_df.withColumn(
                        timestamp_col, _f.col(timestamp_col).cast("timestamp")
                    )
                except Exception as e:
                    raise StreamingError(
                        f"Failed to cast watermark column '{timestamp_col}' to timestamp: {str(e)}",
                        error_code="WATERMARK_CAST_ERROR",
                        cause=e,
                    ) from e

            logger.info(
                f"Applying watermark on column '{timestamp_col}' with delay '{delay_threshold}'"
            )
            return streaming_df.withWatermark(timestamp_col, delay_threshold)

        except Exception as e:
            logger.error(f"Error applying watermark: {str(e)}")
            if isinstance(e, StreamingError):
                raise
            else:
                raise StreamingError(
                    f"Failed to apply watermark: {str(e)}",
                    error_code="WATERMARK_ERROR",
                    cause=e,
                ) from e

    def _apply_transformations(self, input_df: DataFrame, node_config: Dict[str, Any]) -> DataFrame:
        """
        Apply transformations to the streaming DataFrame with error handling.
        """
        try:
            function_config = node_config.get("function")
            if not function_config:
                logger.info("No transformation function specified, using input DataFrame as-is")
                return input_df

            transform_func = self._get_transform_function(function_config)
            function_params = function_config.get("params")

            try:
                transformed_df = self._call_transform_function(
                    transform_func, input_df, function_params
                )
            except StreamingError:
                raise
            except Exception as e:
                raise StreamingError(
                    f"Error executing transformation function: {str(e)}",
                    error_code="TRANSFORMATION_ERROR",
                    context={
                        "function_callable": str(transform_func),
                        "params_provided": bool(function_params),
                    },
                    cause=e,
                ) from e

            if not isinstance(transformed_df, DataFrame):
                raise StreamingError(
                    f"Transformation function must return a DataFrame, got {type(transformed_df)}",
                    error_code="INVALID_RETURN_TYPE",
                    context={
                        "return_type": str(type(transformed_df)),
                    },
                )

            logger.info("Transformation applied successfully")
            return transformed_df

        except Exception as e:
            logger.error(f"Error applying transformation: {str(e)}")
            if isinstance(e, StreamingError):
                raise
            else:
                raise StreamingError(
                    f"Failed to apply transformation: {str(e)}",
                    error_code="TRANSFORMATION_FAILURE",
                    cause=e,
                ) from e

    def _call_transform_function(
        self,
        transform_func: Callable[..., DataFrame],
        input_df: DataFrame,
        params: Optional[Dict[str, Any]],
    ) -> DataFrame:
        """Call transformation with backward-compatible signatures.

        Supported forms:
        - fn(df)
        - fn(df, params)
        """
        safe_params = params if isinstance(params, dict) else {}

        try:
            func_signature = _cached_signature(transform_func)
        except Exception as e:
            raise StreamingError(
                f"Cannot inspect transformation signature: {str(e)}",
                error_code="INVALID_FUNCTION_SIGNATURE",
                context={"function_callable": str(transform_func)},
                cause=e,
            ) from e

        positional_params = [
            p
            for p in func_signature.parameters.values()
            if p.kind
            in (
                Parameter.POSITIONAL_ONLY,
                Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]

        has_var_positional = any(
            p.kind == Parameter.VAR_POSITIONAL for p in func_signature.parameters.values()
        )

        if not positional_params and not has_var_positional:
            raise StreamingError(
                "Transformation function must accept at least one DataFrame argument",
                error_code="INVALID_FUNCTION_SIGNATURE",
                context={"function_callable": str(transform_func)},
            )

        if len(positional_params) > 2 and not has_var_positional:
            raise StreamingError(
                "Transformation function must accept one or two positional arguments",
                error_code="INVALID_FUNCTION_SIGNATURE",
                context={
                    "function_callable": str(transform_func),
                    "positional_parameter_count": len(positional_params),
                },
            )

        if len(positional_params) <= 1 and not has_var_positional:
            if safe_params:
                logger.warning(
                    "Transformation function '{}' accepts only 'df' but 'params' were provided. "
                    "Params will be ignored.",
                    (
                        transform_func.__name__
                        if hasattr(transform_func, "__name__")
                        else str(transform_func)
                    ),
                )
            return transform_func(input_df)

        return transform_func(input_df, safe_params)

    def _get_transform_function(self, function_config: Dict[str, Any]) -> Callable:
        """
        Get transformation function from registry.

        If ``function_config["module"]`` is set the module is imported first so
        its ``register_transforms(registry)`` call has a chance to populate the
        local registry before the key lookup.
        """
        transformation_key = function_config.get("key")
        if not transformation_key:
            raise StreamingConfigurationError(
                "Transformation must specify 'key' to reference a registered transformation",
                config_section="function.key",
            )

        module_path = function_config.get("module")
        if module_path:
            self._auto_import_transform_module(str(module_path))

        return self._get_registered_transformation(transformation_key)

    def _auto_import_transform_module(self, module_path: str) -> None:
        """Import *module_path* and call register_transforms(registry) if defined.

        Idempotent: repeated calls for the same already-registered key are no-ops
        because TransformationRegistry.register raises on duplicate names, so we
        only call register_transforms when the registry is still empty.
        """
        import importlib
        import os
        import sys

        cwd = os.getcwd()
        if cwd not in sys.path:
            sys.path.insert(0, cwd)

        try:
            module = importlib.import_module(module_path)
        except Exception as exc:
            logger.warning(
                "function.module '{}' could not be imported: {}",
                module_path,
                exc,
            )
            return

        fn = getattr(module, "register_transforms", None)
        if callable(fn):
            try:
                fn(self.transformation_registry)
                logger.debug("Auto-registered transforms from module '{}'", module_path)
            except Exception as exc:
                logger.warning(
                    "register_transforms() in '{}' raised: {}",
                    module_path,
                    exc,
                )

    def _get_registered_transformation(self, transformation_key: str) -> Callable:
        """
        Get transformation from the per-manager registry first, then fall back to global registry.
        """
        try:
            # Try local registry first
            transform_func = self.transformation_registry.get(transformation_key)
            logger.info(f"Applying local transformation: '{transformation_key}'")
            return transform_func
        except ValueError:
            logger.debug(f"Transformation not found in local registry: {transformation_key}")

        try:
            # Fall back to the process-wide registry (TransformationRegistry.class_register).
            transform_func = TransformationRegistry.class_get(transformation_key)
            logger.info(f"Applying global transformation: '{transformation_key}'")
            return transform_func
        except ValueError as e:
            available_local = self.transformation_registry.list_transformations()
            available_global = TransformationRegistry.class_list_transformations()
            hint = (
                "To register a transform, call "
                "query_manager.transformation_registry.register(key, fn) "
                "before start_pipeline (see run_streaming_fraud.py for an example), "
                "or TransformationRegistry.class_register(key, fn) for the process-wide registry."
            )
            available = sorted(set(available_local) | set(available_global))
            available_str = ", ".join(available) if available else "(none)"
            raise StreamingConfigurationError(
                f"Transformation '{transformation_key}' not registered. "
                f"Available transformations: [{available_str}]. {hint}",
                config_section="function.key",
                config_value=transformation_key,
                context={
                    "available_transformations": available,
                    "available_local": available_local,
                    "available_global": available_global,
                    "registration_hint": hint,
                },
            ) from e

    def _configure_and_start_query(
        self,
        df: DataFrame,
        node_config: Dict[str, Any],
        execution_id: str,
        pipeline_name: str,
    ) -> Tuple[StreamingQuery, str]:
        """Configure and start the streaming query with comprehensive error handling."""
        try:
            output_config = node_config.get("output", {})
            if not output_config:
                raise StreamingConfigurationError(
                    "Streaming node must have output configuration",
                    config_section="output",
                )

            # Shallow-copy top level + explicit copies of nested mutable dicts to avoid
            # sharing state across nodes without the overhead of deepcopy.
            # Note: "watermark" is deliberately not copied here — it's resolved
            # and applied earlier in _load_streaming_input (streaming.watermark
            # with input.watermark fallback), not read from this local dict.
            _d = DEFAULT_STREAMING_CONFIG
            streaming_config = {
                **_d,
                "trigger": dict(_d["trigger"]),
                "options": dict(_d["options"]),
            }
            streaming_config.update(node_config.get("streaming", {}))

            node_name = node_config.get("name", "unknown")
            query_name = (
                streaming_config.get("query_name") or f"{pipeline_name}_{node_name}_{execution_id}"
            )

            checkpoint_location = self._get_checkpoint_location(
                streaming_config.get("checkpoint_location"),
                pipeline_name,
                node_name,
                execution_id,
            )

            # Validate and reserve checkpoint atomically before Spark operations
            self._validate_and_reserve_checkpoint(checkpoint_location, node_name)

            # From here on the checkpoint is reserved. Any failure before the query
            # is successfully started (invalid trigger, missing format, Spark error)
            # must release the reservation, otherwise the path stays permanently
            # claimed and future retries fail with a misleading "already reserved".
            # On success, ownership transfers to create_and_start_query, which moves
            # the reservation into _active_queries.
            reservation_committed = False
            try:
                output_mode = streaming_config.get("output_mode", StreamingOutputMode.APPEND.value)

                trigger_config = streaming_config.get("trigger", {})
                trigger = self._configure_trigger(trigger_config, query_name)

                logger.info(f"Configuring streaming query '{query_name}':")
                logger.info(f"  - Output mode: {output_mode}")
                logger.info(f"  - Trigger: {trigger_config}")
                logger.info(f"  - Checkpoint: {checkpoint_location}")

                write_stream = (
                    df.writeStream.outputMode(output_mode)
                    .queryName(query_name)
                    .option("checkpointLocation", checkpoint_location)
                )

                if trigger:
                    write_stream = write_stream.trigger(**trigger)

                output_format = output_config.get("format")
                if not output_format:
                    raise StreamingConfigurationError(
                        "Output configuration must specify format",
                        config_section="output.format",
                    )

                writer = self.writer_factory.get_writer(output_format)
                # Serialize the scheduling-conf + .start() window so each query
                # captures its own FAIR pool and shuffle.partitions value.
                with self._query_start_lock:
                    self._apply_query_scheduling(df, node_name, streaming_config)
                    query = writer.write_stream(write_stream, output_config)
                reservation_committed = True
                return query, checkpoint_location
            finally:
                if not reservation_committed:
                    self._release_checkpoint_reservation(checkpoint_location)

        except Exception as e:
            logger.error(f"Error configuring streaming query: {str(e)}")
            if isinstance(e, StreamingError):
                raise
            else:
                raise StreamingQueryError(
                    f"Failed to configure streaming query: {str(e)}",
                    query_name=node_config.get("name", "unknown"),
                    cause=e,
                ) from e

    # ── Delegation to CheckpointManager ─────────────────────────────────────────
    # These thin wrappers keep StreamingQueryManager's internal surface stable
    # (callers and tests use them) while the logic itself lives in
    # ducta.stream.checkpoints.CheckpointManager.

    @staticmethod
    def _is_cloud_path(path: str) -> bool:
        """Check if path is on a cloud filesystem."""
        return CheckpointManager.is_cloud_path(path)

    @staticmethod
    def _sanitize_path_component(component: str) -> str:
        """Sanitize a user-supplied path component to prevent directory traversal."""
        return CheckpointManager.sanitize_path_component(component)

    @staticmethod
    def _build_checkpoint_path(
        checkpoint_base: str,
        pipeline_name: str,
        node_name: str,
        execution_id: str,
    ) -> str:
        """Build the full checkpoint path from base and identifiers."""
        return CheckpointManager.build_checkpoint_path(
            checkpoint_base, pipeline_name, node_name, execution_id
        )

    def _determine_checkpoint_base(self, base_checkpoint: Optional[str]) -> str:
        """Determine the base directory for checkpoints."""
        return self.checkpoint_manager.determine_checkpoint_base(base_checkpoint)

    def _ensure_checkpoint_dir(self, checkpoint_path: str) -> None:
        """Ensure checkpoint directory exists for local filesystems."""
        self.checkpoint_manager.ensure_checkpoint_dir(checkpoint_path)

    def _get_checkpoint_location(
        self,
        base_checkpoint: Optional[str],
        pipeline_name: str,
        node_name: str,
        execution_id: str,
    ) -> str:
        """Get checkpoint location for the streaming query with validation."""
        return self.checkpoint_manager.get_checkpoint_location(
            base_checkpoint, pipeline_name, node_name, execution_id
        )

    def _validate_and_reserve_checkpoint(self, checkpoint_path: str, node_name: str) -> None:
        """Atomically validate and reserve a checkpoint path to prevent concurrent-start races."""
        self.checkpoint_manager.validate_and_reserve(
            checkpoint_path, node_name, self._active_queries, self._active_queries_lock
        )

    def _release_checkpoint_reservation(self, checkpoint_path: str) -> None:
        """Release a reserved checkpoint when Spark startup fails before query registration."""
        self.checkpoint_manager.release_reservation(checkpoint_path, self._active_queries_lock)

    # ── Delegation to TriggerScheduler ──────────────────────────────────────────

    def _configure_trigger(
        self, trigger_config: Dict[str, Any], query_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Configure streaming trigger with minimum interval validation."""
        return self.trigger_scheduler.configure_trigger(trigger_config, query_name)

    def _apply_query_scheduling(
        self, df: DataFrame, node_name: str, streaming_config: Dict[str, Any]
    ) -> None:
        """Pin this query to its own FAIR scheduler pool and tune shuffle partitions.

        Must be called inside ``self._query_start_lock`` and immediately before
        ``.start()`` so the values are captured by *this* query's cloned SQLConf
        and not leaked to / clobbered by concurrent starts.
        """
        self.trigger_scheduler.apply_query_scheduling(df, node_name, streaming_config)

    def stop_query(
        self,
        query: StreamingQuery,
        graceful: bool = True,
        timeout_seconds: float = 30.0,
    ) -> bool:
        """
        Stop a streaming query with timeout and error handling.
        """
        try:
            if not self._is_query_active(query):
                logger.info(f"Query '{self._get_query_name(query)}' is already stopped")
                return True

            logger.info(
                f"Stopping streaming query '{self._get_query_name(query)}' (ID: {self._get_query_id(query)})"
            )

            start_time = time.time()
            self._call_stop_or_set_inactive(query)

            if graceful:
                stopped = self._wait_until_stopped(query, start_time, timeout_seconds)
                if not stopped:
                    raise StreamingTimeoutError(
                        f"Query '{self._get_query_name(query)}' did not stop within {timeout_seconds}s. "
                        f"The query may still be running; check Spark UI or call stop again.",
                        context={
                            "query_id": self._get_query_id(query),
                            "query_name": self._get_query_name(query),
                            "timeout_seconds": timeout_seconds,
                        },
                    )

            self._remove_query_from_active(query)

            logger.info(f"Query '{self._get_query_name(query)}' stopped successfully")
            return True

        except Exception as e:
            logger.error(
                f"Error stopping query '{self._get_query_name(query) or 'unknown'}': {str(e)}"
            )
            raise StreamingQueryError(
                f"Failed to stop query: {str(e)}",
                query_id=self._get_query_id(query),
                query_name=self._get_query_name(query),
                cause=e,
            ) from e

    def _call_stop_or_set_inactive(self, query: StreamingQuery) -> None:
        """
        Invoke the query stop method if available.
        """
        stop_call = getattr(query, "stop", None)
        if callable(stop_call):
            try:
                stop_call()
            except Exception as e:
                logger.debug(
                    "Query '{}' stop() raised an exception (may already be stopped): {}",
                    self._get_query_name(query),
                    e,
                )
        else:
            logger.warning(
                "Query '%s' does not expose a callable stop() method — unable to stop it programmatically.",
                self._get_query_name(query),
            )

    def _wait_until_stopped(
        self, query: StreamingQuery, start_time: float, timeout_seconds: float
    ) -> bool:
        """
        Wait until the query becomes inactive or timeout elapses.

        Prefers query.awaitTermination(timeout) when available (Spark native), falling
        back to a polling loop for mock/test objects.
        """
        try:
            remaining = timeout_seconds - (time.time() - start_time)
            if remaining <= 0:
                return not self._is_query_active(query)

            await_fn = getattr(query, "awaitTermination", None)
            if callable(await_fn):
                try:
                    await_fn(remaining)
                    return not self._is_query_active(query)
                except Exception:
                    pass  # fall through to polling

            # Fallback polling (for test mocks that don't implement awaitTermination)
            while self._is_query_active(query) and (time.time() - start_time) < timeout_seconds:
                time.sleep(0.5)
            return not self._is_query_active(query)
        except Exception:
            return False

    def _remove_query_from_active(self, query: StreamingQuery) -> None:
        """
        Remove query entry from the active queries map if present.
        """
        query_key = None
        target_id = self._get_query_id(query)
        with self._active_queries_lock:
            for key, info in self._active_queries.items():
                try:
                    stored = info.get("query")
                    if stored is query:
                        query_key = key
                        break
                    if target_id is not None and self._get_query_id(stored) == target_id:
                        query_key = key
                        break
                except Exception:
                    continue

            if query_key:
                del self._active_queries[query_key]
