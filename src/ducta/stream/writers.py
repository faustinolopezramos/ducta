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

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

try:
    from pyspark.sql.streaming import DataStreamWriter, StreamingQuery  # type: ignore
except ImportError:  # PySpark not installed (e.g. pure-Python test environments)
    DataStreamWriter = Any  # type: ignore
    StreamingQuery = Any  # type: ignore

from ducta.stream.exceptions import StreamingError, StreamingFormatNotSupportedError


class BaseStreamingWriter(ABC):
    """Base class for streaming data writers."""

    def __init__(self, context):
        self.context = context

    @abstractmethod
    def write_stream(
        self, write_stream: DataStreamWriter, config: Dict[str, Any]
    ) -> StreamingQuery:
        """Write streaming data and return the streaming query."""
        pass

    def _validate_config(
        self, config: Dict[str, Any], required_fields: Optional[list] = None
    ) -> None:
        """Validate basic configuration requirements."""
        if not isinstance(config, dict):
            raise StreamingError("Configuration must be a dictionary")

        req = required_fields or []
        missing_fields = [field for field in req if field not in config]
        if missing_fields:
            raise StreamingError(f"Missing required fields: {missing_fields}")

    def _apply_options(self, writer: DataStreamWriter, options: Dict[str, Any]) -> DataStreamWriter:
        """Apply options to writer with error handling."""
        try:
            for key, value in options.items():
                if value is None:
                    continue
                # Spark expects string values for writer.option
                writer = writer.option(str(key), str(value))
            return writer
        except Exception as e:
            logger.error(f"Error applying options {options}: {str(e)}")
            raise StreamingError(f"Failed to apply writer options: {str(e)}")

    def _apply_common(self, writer: DataStreamWriter, config: Dict[str, Any]) -> DataStreamWriter:
        """
        Apply common streaming settings:
        - outputMode: append|complete|update
        - trigger: {"once": true} | {"processingTime": "10 seconds"} | {"availableNow": true}
        - checkpointLocation: path string
        - queryName: name string
        """
        try:
            options = config.get("options", {}) or {}
            writer = self._apply_options(writer, options)

            output_mode = config.get("outputMode")
            if output_mode:
                writer = writer.outputMode(str(output_mode))

            trigger_cfg = config.get("trigger")
            if trigger_cfg:
                # Pass through supported trigger configs
                # Example: {"once": True} | {"availableNow": True} | {"processingTime": "10 seconds"}
                if isinstance(trigger_cfg, dict):
                    writer = writer.trigger(**trigger_cfg)
                else:
                    # Fallback: if string, assume processing time
                    writer = writer.trigger(processingTime=str(trigger_cfg))

            checkpoint = config.get("checkpointLocation")
            if checkpoint:
                writer = writer.option("checkpointLocation", str(checkpoint))

            query_name = config.get("queryName")
            if query_name:
                writer = writer.queryName(str(query_name))

            return writer
        except Exception as e:
            logger.error(f"Error applying common streaming settings: {str(e)}")
            raise StreamingError(f"Failed to apply common streaming settings: {str(e)}")

    def _apply_partitioning(
        self, writer: DataStreamWriter, config: Dict[str, Any]
    ) -> DataStreamWriter:
        """Apply partitionBy when present."""
        partition_by = config.get("partitionBy")
        if partition_by:
            if isinstance(partition_by, list):
                writer = writer.partitionBy(*partition_by)
            else:
                writer = writer.partitionBy(str(partition_by))
        return writer


class ConsoleStreamingWriter(BaseStreamingWriter):
    """Streaming writer for console output (debugging/testing)."""

    def write_stream(
        self, write_stream: DataStreamWriter, config: Dict[str, Any]
    ) -> StreamingQuery:
        """Write to console."""
        try:
            self._validate_config(config)
            options = config.get("options", {}) or {}

            logger.info("Starting console streaming writer")

            writer = write_stream.format("console")
            writer = self._apply_common(writer, config)

            if "numRows" not in options:
                writer = writer.option("numRows", "20")
            if "truncate" not in options:
                writer = writer.option("truncate", "false")

            return writer.start()

        except StreamingError:
            raise
        except Exception as e:
            logger.error(f"Error starting console streaming writer: {str(e)}")
            raise StreamingError(f"Failed to start console writer: {str(e)}") from e


class BasePathStreamingWriter(BaseStreamingWriter):
    """Base class for streaming writers that write to file paths."""

    FORMAT_NAME: str = "unknown"

    def _write_to_path(
        self, write_stream: DataStreamWriter, config: Dict[str, Any], format_name: str
    ) -> StreamingQuery:
        """Template method for path-based writers."""
        try:
            self._validate_config(config, required_fields=["path"])
            path = config.get("path")

            # Validate path is non-empty string
            if not path or not isinstance(path, str) or not path.strip():
                raise StreamingError(
                    f"{format_name} path must be a non-empty string, got: {repr(path)}"
                )

            logger.info(f"Starting {format_name} streaming writer to path: {path}")

            writer = write_stream.format(format_name)
            writer = self._apply_common(writer, config)
            writer = self._apply_partitioning(writer, config)

            return writer.start(str(path))

        except StreamingError:
            # Preserve the original streaming error (e.g. validation) instead of
            # re-wrapping it in a generic "Failed to start" message.
            raise
        except Exception as e:
            logger.error(f"Error starting {format_name} streaming writer: {str(e)}")
            raise StreamingError(f"Failed to start {format_name} writer: {str(e)}") from e


class DeltaStreamingWriter(BasePathStreamingWriter):
    """Streaming writer for Delta Lake."""

    FORMAT_NAME = "delta"

    def write_stream(
        self, write_stream: DataStreamWriter, config: Dict[str, Any]
    ) -> StreamingQuery:
        """Write to Delta table, injecting Delta-specific defaults before delegating."""
        # Inject Delta-specific defaults without mutating the original config.
        # enableChangeDataFeed is set so downstream CDF readers (silver/gold/score
        # nodes) can consume inserts/updates from this table via readChangeFeed.
        options = dict(config.get("options", {}) or {})
        if "mergeSchema" not in options:
            options["mergeSchema"] = "true"
        if "delta.enableChangeDataFeed" not in options:
            options["delta.enableChangeDataFeed"] = "true"
        merged_config = {**config, "options": options}
        return self._write_to_path(write_stream, merged_config, self.FORMAT_NAME)


class ParquetStreamingWriter(BasePathStreamingWriter):
    """Streaming writer for Parquet files."""

    FORMAT_NAME = "parquet"

    def write_stream(
        self, write_stream: DataStreamWriter, config: Dict[str, Any]
    ) -> StreamingQuery:
        """Write to Parquet files."""
        return self._write_to_path(write_stream, config, self.FORMAT_NAME)


class KafkaStreamingWriter(BaseStreamingWriter):
    """Streaming writer for Apache Kafka."""

    def write_stream(
        self, write_stream: DataStreamWriter, config: Dict[str, Any]
    ) -> StreamingQuery:
        """Write to Kafka."""
        try:
            self._validate_config(config)
            options = config.get("options", {}) or {}

            required_kafka_options = ["kafka.bootstrap.servers", "topic"]
            missing_options = [opt for opt in required_kafka_options if not options.get(opt)]
            if missing_options:
                raise StreamingError(f"Missing required Kafka options: {missing_options}")

            topic = options.get("topic")
            logger.info(f"Starting Kafka streaming writer to topic: {topic}")

            writer = write_stream.format("kafka")
            writer = self._apply_common(writer, config)

            # Kafka sink does not use partitionBy. Options already applied in _apply_common.
            return writer.start()

        except StreamingError:
            raise
        except Exception as e:
            logger.error(f"Error starting Kafka streaming writer: {str(e)}")
            raise StreamingError(f"Failed to start Kafka writer: {str(e)}") from e


class JSONStreamingWriter(BasePathStreamingWriter):
    """Streaming writer for JSON files."""

    FORMAT_NAME = "json"

    def write_stream(
        self, write_stream: DataStreamWriter, config: Dict[str, Any]
    ) -> StreamingQuery:
        """Write to JSON files."""
        return self._write_to_path(write_stream, config, self.FORMAT_NAME)


class CSVStreamingWriter(BasePathStreamingWriter):
    """Streaming writer for CSV files."""

    FORMAT_NAME = "csv"

    def write_stream(
        self, write_stream: DataStreamWriter, config: Dict[str, Any]
    ) -> StreamingQuery:
        """Write to CSV files, injecting header=true default before delegating."""
        # Inject CSV-specific default (header) without mutating the original config
        options = dict(config.get("options", {}) or {})
        if "header" not in options:
            options["header"] = "true"
        merged_config = {**config, "options": options}
        return self._write_to_path(write_stream, merged_config, self.FORMAT_NAME)


class StreamingWriterFactory:
    """Factory for creating streaming data writers."""

    def __init__(self, context):
        self.context = context
        # Maps format_name -> instantiated writer (populated on first access)
        self._writers: Dict[str, BaseStreamingWriter] = {}
        self._register_builtin_classes()
        logger.info(
            f"StreamingWriterFactory ready with formats: {list(self._writer_classes.keys())}"
        )

    def _register_builtin_classes(self) -> None:
        """Register built-in writer classes without instantiating them.

        ``_writer_classes`` maps ``format_name -> (cls, extra_args, extra_kwargs)``
        so that *args/**kwargs passed to :meth:`register_custom_writer` are
        forwarded to the writer constructor on first instantiation.
        """
        self._writer_classes: Dict[str, tuple] = {
            "console": (ConsoleStreamingWriter, (), {}),
            "delta": (DeltaStreamingWriter, (), {}),
            "parquet": (ParquetStreamingWriter, (), {}),
            "kafka": (KafkaStreamingWriter, (), {}),
            "json": (JSONStreamingWriter, (), {}),
            "csv": (CSVStreamingWriter, (), {}),
        }

    def _get_or_create_writer(self, format_key: str) -> BaseStreamingWriter:
        """Lazily instantiate and cache a writer for the given format key."""
        if format_key not in self._writers:
            cls, extra_args, extra_kwargs = self._writer_classes[format_key]
            try:
                self._writers[format_key] = cls(self.context, *extra_args, **extra_kwargs)
            except Exception as e:
                raise StreamingError(
                    f"Failed to instantiate writer for format '{format_key}': {str(e)}",
                    cause=e,
                ) from e
        return self._writers[format_key]

    def get_writer(self, format_name: str) -> BaseStreamingWriter:
        """Get streaming writer for specified format."""
        try:
            if not format_name or not isinstance(format_name, str):
                raise StreamingError("Format name must be a non-empty string")

            format_key = format_name.lower()

            if format_key not in self._writer_classes:
                supported_formats = list(self._writer_classes.keys())
                raise StreamingFormatNotSupportedError(
                    f"Streaming format '{format_name}' not supported. "
                    f"Supported formats: {supported_formats}"
                )

            return self._get_or_create_writer(format_key)

        except Exception as e:
            logger.error(f"Error getting writer for format '{format_name}': {str(e)}")
            raise

    def list_supported_formats(self) -> list:
        """List all supported streaming output formats."""
        return list(self._writer_classes.keys())

    def register_custom_writer(self, format_name: str, writer_class, *args, **kwargs):
        """Register a custom streaming writer.

        ``*args`` and ``**kwargs`` are stored and forwarded to the writer
        constructor on its first use, alongside the mandatory ``context`` arg.
        """
        try:
            if not issubclass(writer_class, BaseStreamingWriter):
                raise StreamingError("Custom writer must inherit from BaseStreamingWriter")
            # Store (class, extra_args, extra_kwargs) so they are forwarded at instantiation.
            self._writer_classes[format_name.lower()] = (writer_class, args, kwargs)
            # If already cached, invalidate so the new class is used
            self._writers.pop(format_name.lower(), None)
            logger.info(f"Registered custom writer '{format_name}'")
        except Exception as e:
            logger.error(f"Error registering custom writer '{format_name}': {str(e)}")
            raise StreamingError(f"Failed to register custom writer: {str(e)}")
