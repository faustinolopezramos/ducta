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

from ducta.stream.constants import (
    DEFAULT_ADAPTIVE_BASE_INTERVAL,
    DEFAULT_STREAMING_CONFIG,
    STREAMING_BACKPRESSURE_DEFAULTS,
    STREAMING_FORMAT_CONFIGS,
    STREAMING_VALIDATIONS,
    PipelineType,
    StreamingConfigDefaults,
    StreamingFormat,
    StreamingOutputMode,
    StreamingTrigger,
)
from ducta.stream.exceptions import (
    StreamingConfigurationError,
    StreamingError,
    StreamingFormatNotSupportedError,
    StreamingPipelineError,
    StreamingQueryError,
    StreamingTimeoutError,
    StreamingValidationError,
    create_error_context,
    handle_streaming_error,
)
from ducta.stream.pipeline_manager import QueryHealthMonitor, StreamingPipelineManager
from ducta.stream.progress_listener import (
    DuctaProgressListener,
    StreamingProgressSink,
    listener_available,
)
from ducta.stream.query_manager import StreamingQueryManager, TransformationRegistry
from ducta.stream.readers import (
    BaseStreamingReader,
    DeltaStreamingReader,
    FileStreamReader,
    KafkaStreamingReader,
    KinesisStreamingReader,
    StreamingReaderFactory,
)
from ducta.stream.validators import StreamingValidator
from ducta.stream.writers import (
    BasePathStreamingWriter,
    BaseStreamingWriter,
    ConsoleStreamingWriter,
    CSVStreamingWriter,
    DeltaStreamingWriter,
    JSONStreamingWriter,
    KafkaStreamingWriter,
    ParquetStreamingWriter,
    StreamingWriterFactory,
)

__all__ = [
    "DEFAULT_ADAPTIVE_BASE_INTERVAL",
    "DEFAULT_STREAMING_CONFIG",
    "STREAMING_BACKPRESSURE_DEFAULTS",
    "STREAMING_FORMAT_CONFIGS",
    "STREAMING_VALIDATIONS",
    "PipelineType",
    "StreamingConfigDefaults",
    "StreamingFormat",
    "StreamingOutputMode",
    "StreamingTrigger",
    "StreamingConfigurationError",
    "StreamingError",
    "StreamingFormatNotSupportedError",
    "StreamingPipelineError",
    "StreamingQueryError",
    "StreamingTimeoutError",
    "StreamingValidationError",
    "create_error_context",
    "handle_streaming_error",
    "DuctaProgressListener",
    "StreamingProgressSink",
    "listener_available",
    "StreamingPipelineManager",
    "QueryHealthMonitor",
    "StreamingQueryManager",
    "TransformationRegistry",
    "BaseStreamingReader",
    "DeltaStreamingReader",
    "FileStreamReader",
    "KafkaStreamingReader",
    "KinesisStreamingReader",
    "StreamingReaderFactory",
    "StreamingValidator",
    "BasePathStreamingWriter",
    "BaseStreamingWriter",
    "CSVStreamingWriter",
    "ConsoleStreamingWriter",
    "DeltaStreamingWriter",
    "JSONStreamingWriter",
    "KafkaStreamingWriter",
    "ParquetStreamingWriter",
    "StreamingWriterFactory",
]
