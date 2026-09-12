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
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

try:
    from pyspark.sql import DataFrame  # type: ignore
    from pyspark.sql.functions import col, from_json  # type: ignore
    from pyspark.sql.types import StructType  # type: ignore
except ImportError:  # PySpark not installed (e.g. pure-Python test environments)
    DataFrame = Any  # type: ignore
    col = None  # type: ignore
    from_json = None  # type: ignore
    StructType = Any  # type: ignore

from ducta.stream.constants import (
    STREAMING_BACKPRESSURE_DEFAULTS,
    STREAMING_FORMAT_CONFIGS,
    StreamingFormat,
)
from ducta.stream.context_utils import get_context_value
from ducta.stream.exceptions import StreamingError
from ducta.stream.factories import StreamingHandlerFactory


class _StreamingSparkMixin:
    """Helper mixin to access SparkSession from dict or object context."""

    @property
    def spark(self):
        ctx = getattr(self, "context", None)
        if ctx is None:
            raise StreamingError("Context is not set in streaming reader")
        spark = get_context_value(ctx, "spark")
        if spark is None:
            raise StreamingError("Spark session is not available in context")
        return spark

    def _spark_read_stream(self):
        return self.spark.readStream


class BaseStreamingReader(ABC, _StreamingSparkMixin):
    """Base class for streaming data readers."""

    FORMAT_NAME: str = "Unknown"

    def __init__(self, context):
        self.context = context

    @abstractmethod
    def read_stream(self, config: Dict[str, Any]) -> DataFrame:
        """Read streaming data and return a streaming DataFrame."""
        raise NotImplementedError

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        """Interpret a config flag that may be a bool or a string like 'false'."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def _validate_options(self, config: Dict[str, Any], format_name: str = None) -> None:
        """Validate required options for the streaming format."""
        try:
            format_key = format_name or self.FORMAT_NAME
            format_config = STREAMING_FORMAT_CONFIGS.get(format_key, {}) or {}
            required_options = format_config.get("required_options", []) or []
            provided_options = config.get("options", {}) or {}
            missing_options = [
                opt
                for opt in required_options
                if provided_options.get(opt) is None and config.get(opt) is None
            ]
            if missing_options:
                raise StreamingError(
                    f"Missing required options for {format_key}: {missing_options}"
                )
        except Exception as e:
            logger.error(
                f"Error validating options for {format_name or self.FORMAT_NAME}: {str(e)}"
            )
            raise

    def _backpressure_disabled(self) -> bool:
        """Read the global opt-out flag for default backpressure limits."""
        ctx = getattr(self, "context", None)
        try:
            gs = get_context_value(ctx, "global_config", {}) or {}
            return self._coerce_bool(gs.get("streaming_disable_backpressure_defaults", False))
        except Exception:
            return False

    def _merge_backpressure_defaults(
        self, options: Dict[str, Any], format_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Inject per-format backpressure limits for any option the user omitted.

        Caps micro-batch size to keep CPU flat during catch-up. User-provided
        values always win; honours the global opt-out flag.
        """
        defaults = STREAMING_BACKPRESSURE_DEFAULTS.get(format_key or self.FORMAT_NAME, {})
        if not defaults or self._backpressure_disabled():
            return options

        merged = dict(options or {})
        for opt, default_value in defaults.items():
            if merged.get(opt) is None:
                merged[opt] = default_value
                logger.debug(
                    "Applying default backpressure limit {}={} for format '{}'",
                    opt,
                    default_value,
                    format_key or self.FORMAT_NAME,
                )
        return merged

    def _apply_options(self, reader, options: Dict[str, Any]):
        """Safely apply reader.options, skipping None values and casting to str."""
        try:
            for key, value in (options or {}).items():
                if value is None:
                    continue
                reader = reader.option(str(key), str(value))
            return reader
        except Exception as e:
            logger.error(f"Error applying options {list((options or {}).keys())}: {str(e)}")
            raise StreamingError(f"Failed to apply reader options: {str(e)}")

    def _ensure_schema(self, schema_cfg: Any) -> Optional["StructType"]:
        """Accept StructType or DDL string; return StructType or None."""
        if schema_cfg is None:
            return None
        try:
            struct_type_cls = StructType if isinstance(StructType, type) else None
            if struct_type_cls and isinstance(schema_cfg, struct_type_cls):
                return schema_cfg
            if isinstance(schema_cfg, str):
                ddl_schema = schema_cfg.strip()
                if not ddl_schema:
                    return None

                from_ddl = getattr(StructType, "fromDDL", None)
                if callable(from_ddl):
                    return from_ddl(ddl_schema)

                # Fallback for PySpark versions that do not expose StructType.fromDDL.
                return self.spark.createDataFrame([], ddl_schema).schema

            logger.warning("json_schema provided but not a StructType or DDL string; ignoring")
            return None
        except Exception as e:
            logger.error(f"Error parsing json_schema: {str(e)}")
            raise StreamingError(f"Failed to parse json_schema: {str(e)}")


class KafkaStreamingReader(BaseStreamingReader):
    """Streaming reader for Apache Kafka."""

    FORMAT_NAME = StreamingFormat.KAFKA.value

    def _augment_kafka_missing_datasource_message(self, error_message: str) -> str:
        """Provide actionable guidance when Spark Kafka connector is missing."""
        lower_msg = (error_message or "").lower()
        if "failed to find data source: kafka" not in lower_msg:
            return error_message

        spark_version = "3.5.0"
        try:
            detected = str(getattr(self.spark, "version", "")).strip()
            if detected:
                major_minor = ".".join(detected.split(".")[:2])
                spark_version = f"{major_minor}.0" if major_minor else detected
        except Exception:
            pass

        package = f"org.apache.spark:spark-sql-kafka-0-10_2.12:{spark_version}"
        return (
            f"{error_message}. Configure global_config.spark_config with "
            f"'spark.jars.packages={package}' and restart the pipeline."
        )

    def read_stream(self, config: Dict[str, Any]) -> DataFrame:
        """Read from Kafka stream."""
        try:
            self._validate_options(config, self.FORMAT_NAME)
            options = config.get("options", {}) or {}

            bs = options.get("kafka.bootstrap.servers")
            logger.info(f"Creating Kafka streaming reader (bootstrap servers: {bs})")

            subscription_options = ["subscribe", "subscribePattern", "assign"]
            provided_subscriptions = [opt for opt in subscription_options if opt in options]
            if len(provided_subscriptions) != 1:
                raise StreamingError(
                    f"Exactly one of {subscription_options} must be provided for Kafka stream"
                )

            reader = self._spark_read_stream().format("kafka")
            reader = self._apply_options(reader, self._merge_backpressure_defaults(options))
            streaming_df = reader.load()

            if config.get("parse_json", False):
                schema = self._ensure_schema(config.get("json_schema"))
                if schema:
                    streaming_df = streaming_df.select(
                        from_json(col("value").cast("string"), schema).alias("data"),
                        col("timestamp"),
                        col("topic"),
                        col("partition"),
                        col("offset"),
                    ).select("data.*", "timestamp", "topic", "partition", "offset")
                else:
                    logger.warning("parse_json=True but no valid json_schema provided")

            return streaming_df

        except StreamingError:
            raise
        except Exception as e:
            original = str(e)
            enriched = self._augment_kafka_missing_datasource_message(original)
            logger.error(f"Error creating Kafka streaming reader: {enriched}")
            raise StreamingError(f"Failed to create Kafka stream: {enriched}") from e


class DeltaStreamingReader(BaseStreamingReader):
    """Streaming reader for Delta Lake change data feed."""

    FORMAT_NAME = StreamingFormat.DELTA_STREAM.value

    def read_stream(self, config: Dict[str, Any]) -> DataFrame:
        try:
            self._validate_options(config, self.FORMAT_NAME)
            options = dict(config.get("options", {}) or {})
            path = config.get("path")

            if not path:
                raise StreamingError(f"{self.FORMAT_NAME} requires 'path' in config")

            path_str = str(path)

            if self._coerce_bool(config.get("auto_enable_cdf", True)):
                self._ensure_cdf_enabled(path_str, options)

            logger.info(f"Creating Delta CDF streaming reader with options: {list(options.keys())}")

            reader = self._spark_read_stream().format("delta")
            reader = self._apply_options(reader, self._merge_backpressure_defaults(options))
            return reader.load(path_str)

        except StreamingError:
            raise
        except Exception as e:
            logger.error(f"Error creating Delta streaming reader: {str(e)}")
            raise StreamingError(f"Failed to create Delta stream: {str(e)}") from e

    def _ensure_cdf_enabled(self, path: str, options: dict) -> None:
        """Enable CDF on an existing Delta table if it was created without it.

        When CDF was not active for historical versions, also injects
        startingVersion=latest so the reader skips non-CDF history and starts
        clean from the current table state.
        """
        try:
            from delta.tables import DeltaTable  # type: ignore
        except ImportError:
            return

        import os

        spark = self.spark
        try:
            # Avoid issues with relative paths in ALTER TABLE statements.
            if "://" not in str(path) and not os.path.isabs(path):
                path = os.path.abspath(path)

            if not DeltaTable.isDeltaTable(spark, path):
                return  # table doesn't exist yet — nothing to do

            detail = DeltaTable.forPath(spark, path).detail().collect()[0]
            properties = detail["properties"] or {}
            cdf_on = str(properties.get("delta.enableChangeDataFeed", "false")).lower() == "true"

            if not cdf_on:
                logger.warning(
                    "Delta table at '{}' has no CDF history. "
                    "Enabling CDF and starting from latest version.",
                    path,
                )
                # Escape backticks (double them, the standard Spark SQL escape for
                # backtick-quoted identifiers) so a path containing one cannot break
                # out of the identifier and inject arbitrary SQL into this statement.
                escaped_path = path.replace("`", "``")
                spark.sql(
                    f"ALTER TABLE delta.`{escaped_path}` "
                    f"SET TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')"
                )
                # Don't try to replay history that was never CDF-tracked.
                if "startingVersion" not in options and "startingTimestamp" not in options:
                    options["startingVersion"] = "latest"
        except Exception as e:
            # This failure is easy to miss: the caller proceeds to start the
            # stream regardless, but CDF is still disabled on the table and
            # `startingVersion=latest` (meant to skip non-CDF history) was
            # never set — the stream may replay old, non-CDF-tracked history
            # under change-data-feed read semantics, producing unexpected
            # rows/columns rather than a clean failure.
            logger.warning(
                "Could not auto-enable CDF on Delta table at '{}': {}. The stream will "
                "proceed with CDF still disabled on this table — it may read historical, "
                "non-CDF-tracked versions under change-data-feed semantics. Enable CDF "
                "manually (ALTER TABLE ... SET TBLPROPERTIES "
                "('delta.enableChangeDataFeed' = 'true')) or set startingVersion/"
                "startingTimestamp explicitly to avoid this.",
                path,
                e,
            )


class FileStreamReader(BaseStreamingReader):
    """Streaming reader for file-based sources (JSON, CSV, Parquet, Text, etc.)."""

    FORMAT_NAME = StreamingFormat.FILE_STREAM.value

    def read_stream(self, config: Dict[str, Any]) -> DataFrame:
        """Read from a file stream source."""
        try:
            self._validate_options(config, self.FORMAT_NAME)
            options = config.get("options", {}) or {}
            path = config.get("path") or options.get("path")

            if config.get("path") and not options.get("path"):
                logger.warning(
                    "FileStreamReader: 'path' at the top level of the input config is deprecated. "
                    "Move it to input.options.path instead."
                )

            if not path:
                raise StreamingError(f"{self.FORMAT_NAME} requires 'path' in config or options")

            file_format = config.get("file_format", "parquet")

            logger.info(f"Creating file stream reader (format={file_format}, path={path})")

            reader = self._spark_read_stream().format(str(file_format))

            reader_options = {k: v for k, v in options.items() if k != "path"}
            reader = self._apply_options(reader, self._merge_backpressure_defaults(reader_options))

            schema = self._ensure_schema(config.get("schema"))
            if schema:
                reader = reader.schema(schema)

            return reader.load(str(path))

        except StreamingError:
            raise
        except Exception as e:
            logger.error(f"Error creating file stream reader: {str(e)}")
            raise StreamingError(f"Failed to create file stream: {str(e)}") from e


class KinesisStreamingReader(BaseStreamingReader):
    """Streaming reader for Amazon Kinesis."""

    FORMAT_NAME = StreamingFormat.KINESIS.value

    def read_stream(self, config: Dict[str, Any]) -> DataFrame:
        try:
            self._validate_options(config, self.FORMAT_NAME)
            options = config.get("options", {}) or {}

            stream_name = options.get("streamName")
            region = options.get("region")

            logger.info(
                f"Creating Kinesis streaming reader (stream={stream_name}, region={region})"
            )

            reader = self._spark_read_stream().format("kinesis")
            reader = self._apply_options(reader, self._merge_backpressure_defaults(options))
            return reader.load()

        except StreamingError:
            raise
        except Exception as e:
            logger.error(f"Error creating Kinesis streaming reader: {str(e)}")
            raise StreamingError(f"Failed to create Kinesis stream: {str(e)}") from e


class StreamingReaderFactory(StreamingHandlerFactory):
    """Factory for creating streaming data readers."""

    _KIND = "reader"
    _BASE_CLASS = BaseStreamingReader

    def _register_builtin_classes(self) -> None:
        """Register built-in reader classes without instantiating them."""
        self._classes = {
            StreamingFormat.KAFKA.value: (KafkaStreamingReader, (), {}),
            StreamingFormat.DELTA_STREAM.value: (DeltaStreamingReader, (), {}),
            StreamingFormat.FILE_STREAM.value: (FileStreamReader, (), {}),
            StreamingFormat.KINESIS.value: (KinesisStreamingReader, (), {}),
        }

    def get_reader(self, format_name: str) -> BaseStreamingReader:
        """Get streaming reader for specified format."""
        return self.get(format_name)

    def register_custom_reader(self, format_name: str, reader_class, *args, **kwargs):
        """Register a custom streaming reader.

        ``*args`` and ``**kwargs`` are stored and forwarded to the reader
        constructor on its first use, alongside the mandatory ``context`` arg.
        """
        self.register_custom(format_name, reader_class, *args, **kwargs)
