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

from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.stream.constants import (
    DEFAULT_ADAPTIVE_BASE_INTERVAL,
    STREAMING_VALIDATIONS,
    StreamingTrigger,
)
from ducta.stream.context_utils import get_context_value
from ducta.stream.exceptions import StreamingConfigurationError, StreamingError

DEFAULT_PROCESSING_TIME_INTERVAL = "10 seconds"


class TriggerScheduler:
    """Resolves streaming trigger config and per-query scheduling (shuffle
    partitions / FAIR pool). Extracted from StreamingQueryManager (composition,
    not inheritance) so trigger logic can be tested and reasoned about in isolation.
    """

    def __init__(self, context: Any, validator: Any, progress_sink: Optional[Any] = None):
        self.context = context
        self.validator = validator
        self.progress_sink = progress_sink

    def configure_trigger(
        self, trigger_config: Dict[str, Any], query_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Configure streaming trigger with minimum interval validation."""
        try:
            trigger_type_raw = trigger_config.get("type", StreamingTrigger.PROCESSING_TIME.value)
            trigger_type = str(trigger_type_raw).lower()

            mapped_key = self._map_trigger_type(trigger_type, trigger_type_raw)

            if mapped_key == "processingTime":
                return self._build_processing_time_trigger(trigger_config)

            if mapped_key == "once":
                return {"once": True}

            if mapped_key == "continuous":
                return self._build_continuous_trigger(trigger_config)

            if mapped_key == "availableNow":
                return {"availableNow": True}

            if mapped_key == "adaptive":
                return self._build_adaptive_trigger(trigger_config, query_name)

            raise StreamingConfigurationError(
                f"Unhandled trigger mapping '{mapped_key}'",
                config_section="trigger.type",
                config_value=mapped_key,
            )

        except Exception as e:
            logger.error(f"Error configuring trigger: {str(e)}")
            if isinstance(e, StreamingError):
                raise
            else:
                raise StreamingConfigurationError(
                    f"Failed to configure trigger: {str(e)}",
                    config_section="trigger",
                    cause=e,
                ) from e

    def _map_trigger_type(self, trigger_type: str, trigger_type_raw: Any) -> str:
        """Map raw trigger type to internal key and validate it."""
        trigger_map = {
            StreamingTrigger.PROCESSING_TIME.value.lower(): "processingTime",
            StreamingTrigger.ONCE.value.lower(): "once",
            StreamingTrigger.CONTINUOUS.value.lower(): "continuous",
            StreamingTrigger.AVAILABLE_NOW.value.lower(): "availableNow",
            "adaptive": "adaptive",
        }
        valid_triggers = list(trigger_map.keys())
        if trigger_type not in valid_triggers:
            raise StreamingConfigurationError(
                f"Invalid trigger type '{trigger_type_raw}'. Valid types: {valid_triggers}",
                config_section="trigger.type",
                config_value=trigger_type_raw,
            )
        return trigger_map[trigger_type]

    def _validate_interval(self, interval: str, config_section: str) -> None:
        """Validate an interval string and ensure it meets minimum configured seconds."""
        if not self.validator.validate_time_interval(interval):
            raise StreamingConfigurationError(
                f"Invalid {config_section.split('.')[-1]} interval '{interval}'",
                config_section=config_section,
                config_value=interval,
            )
        min_interval = float(STREAMING_VALIDATIONS.get("min_trigger_interval_seconds", 1))
        if self.validator.parse_time_to_seconds(interval) < min_interval:
            raise StreamingConfigurationError(
                f"{config_section.split('.')[-1]} interval '{interval}' is below minimum of {min_interval} seconds",
                config_section=config_section,
                config_value=interval,
            )

    def _build_processing_time_trigger(self, trigger_config: Dict[str, Any]) -> Dict[str, Any]:
        """Build processingTime trigger dict after validation."""
        interval = str(trigger_config.get("interval", DEFAULT_PROCESSING_TIME_INTERVAL))
        self._validate_interval(interval, "trigger.interval")
        return {"processingTime": interval}

    def _build_continuous_trigger(self, trigger_config: Dict[str, Any]) -> Dict[str, Any]:
        """Build continuous trigger dict after validation."""
        interval = str(trigger_config.get("interval", "1 second"))
        self._validate_interval(interval, "trigger.interval")
        return {"continuous": interval}

    def _global_setting(self, key: str, default: Any) -> Any:
        """Read a value from context.global_settings with a safe fallback."""
        try:
            gs = get_context_value(self.context, "global_settings", {}) or {}
            if isinstance(gs, dict) and gs.get(key) is not None:
                return gs.get(key)
        except Exception:
            pass
        return default

    def _build_adaptive_trigger(
        self, trigger_config: Dict[str, Any], query_name: Optional[str]
    ) -> Dict[str, Any]:
        """Build a processingTime trigger whose interval adapts to observed load.

        Structured Streaming fixes a query's trigger interval at start time and
        cannot change it without a restart, so "adaptive" derives the *starting*
        interval from historical batch durations captured by the progress sink
        on previous runs of this query (proportional controller targeting ~66%
        trigger utilisation). With no history it falls back to a configurable
        base interval. The chosen value is always clamped to
        [min_trigger_interval_seconds, ceiling].
        """
        min_interval = float(STREAMING_VALIDATIONS.get("min_trigger_interval_seconds", 1))
        ceiling = float(self._global_setting("streaming_adaptive_max_interval_seconds", 60.0))
        # An explicit interval acts as the base/preferred value when set.
        base_raw = trigger_config.get("interval") or self._global_setting(
            "streaming_adaptive_base_interval", DEFAULT_ADAPTIVE_BASE_INTERVAL
        )

        chosen_interval = str(base_raw)
        avg_trigger_ms = None
        if query_name and self.progress_sink is not None:
            try:
                avg_trigger_ms = self.progress_sink.avg_trigger_ms(query_name)
            except Exception:
                avg_trigger_ms = None

        if avg_trigger_ms is not None and avg_trigger_ms > 0:
            # Target ~66% utilisation: leave headroom so batches finish within
            # the interval rather than queueing (which inflates latency + CPU).
            target_seconds = (avg_trigger_ms / 1000.0) * 1.5
            clamped = max(min_interval, min(ceiling, target_seconds))
            chosen_interval = f"{clamped:.3f} seconds"
            logger.info(
                "Adaptive trigger for '{}': avg triggerExecution {:.0f}ms -> interval {}",
                query_name,
                avg_trigger_ms,
                chosen_interval,
            )
        else:
            logger.info(
                "Adaptive trigger for '{}': no history, using base interval {}",
                query_name or "unknown",
                chosen_interval,
            )

        self._validate_interval(chosen_interval, "trigger.interval")
        return {"processingTime": chosen_interval}

    def _effective_shuffle_partitions(self, spark: Any, streaming_config: Dict[str, Any]):
        """Resolve the shuffle partition count to apply to this streaming query.

        Streaming (esp. stateful) queries don't benefit from AQE coalesce, so the
        global default of 200 means 200 tasks + 200 state files *per micro-batch*.
        Precedence: per-node ``streaming.shuffle_partitions`` >
        ``global_settings.streaming_shuffle_partitions`` > a computed default of
        ``clamp(2 x defaultParallelism, 8, 64)``. Returns None to leave Spark's
        own value untouched (e.g. when parallelism can't be read).
        """
        override = streaming_config.get("shuffle_partitions")
        if override is None:
            override = self._global_setting("streaming_shuffle_partitions", None)
        if override is not None:
            try:
                value = int(override)
                return value if value > 0 else None
            except (TypeError, ValueError):
                logger.warning("Ignoring non-integer shuffle_partitions override: {}", override)
                return None
        try:
            parallelism = int(spark.sparkContext.defaultParallelism)
        except Exception:
            return None
        return max(8, min(64, 2 * parallelism))

    def apply_query_scheduling(
        self, df: Any, node_name: str, streaming_config: Dict[str, Any]
    ) -> None:
        """Pin this query to its own FAIR scheduler pool and tune shuffle partitions.

        Must be called by the caller inside its own query-start lock and
        immediately before ``.start()`` so the values are captured by *this*
        query's cloned SQLConf and not leaked to / clobbered by concurrent starts.
        """
        spark = getattr(df, "sparkSession", None) or getattr(df, "sql_ctx", None)
        if spark is None:
            return
        spark_session = getattr(spark, "sparkSession", spark)
        try:
            sc = spark_session.sparkContext
            # FAIR pool per query so a heavy stream can't starve the others.
            sc.setLocalProperty("spark.scheduler.pool", f"streaming_{node_name}")
        except Exception as e:
            logger.debug("Could not set scheduler pool for '{}': {}", node_name, e)

        partitions = self._effective_shuffle_partitions(spark_session, streaming_config)
        if partitions is not None:
            try:
                spark_session.conf.set("spark.sql.shuffle.partitions", str(partitions))
                logger.info("Streaming query '{}': shuffle.partitions={}", node_name, partitions)
            except Exception as e:
                logger.debug("Could not set shuffle.partitions for '{}': {}", node_name, e)
