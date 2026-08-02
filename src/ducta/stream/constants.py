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

from enum import Enum
from typing import Any, Dict, Optional, TypedDict


class PipelineType(Enum):
    """Types of pipelines supported by the framework."""

    BATCH = "batch"
    STREAMING = "streaming"
    HYBRID = "hybrid"
    ML = "ml"


class StreamingTrigger(Enum):
    """Streaming trigger types."""

    PROCESSING_TIME = "processing_time"
    ONCE = "once"
    CONTINUOUS = "continuous"
    AVAILABLE_NOW = "available_now"


class StreamingFormat(Enum):
    """Supported streaming data formats."""

    KAFKA = "kafka"
    KINESIS = "kinesis"
    DELTA_STREAM = "delta_stream"
    FILE_STREAM = "file_stream"


class StreamingOutputMode(Enum):
    """Streaming output modes."""

    APPEND = "append"
    UPDATE = "update"
    COMPLETE = "complete"


class _TriggerDefaults(TypedDict):
    type: str
    interval: str


class _WatermarkDefaults(TypedDict):
    column: Optional[str]
    delay: str


class StreamingConfigDefaults(TypedDict):
    trigger: _TriggerDefaults
    output_mode: str
    checkpoint_location: Optional[str]
    query_name: Optional[str]
    watermark: _WatermarkDefaults
    options: Dict[str, Any]


# Configuraciones por defecto para streaming
DEFAULT_STREAMING_CONFIG: StreamingConfigDefaults = {
    "trigger": {
        "type": StreamingTrigger.PROCESSING_TIME.value,
        "interval": "10 seconds",
    },
    "output_mode": StreamingOutputMode.APPEND.value,
    "checkpoint_location": None,  # resolved at runtime; see StreamingQueryManager._determine_checkpoint_base
    "query_name": None,
    "watermark": {"column": None, "delay": "10 seconds"},
    "options": {},
}

# Format-specific configurations.
# Only ``required_options`` is consumed (by readers and the validator); the set of
# optional options is delegated to Spark's own data-source validation.
STREAMING_FORMAT_CONFIGS: Dict[str, Dict[str, Any]] = {
    StreamingFormat.KAFKA.value: {
        "required_options": ["kafka.bootstrap.servers"],
    },
    StreamingFormat.DELTA_STREAM.value: {
        "required_options": [],
    },
    StreamingFormat.FILE_STREAM.value: {
        "required_options": ["path"],
    },
    StreamingFormat.KINESIS.value: {
        "required_options": ["streamName", "region"],
    },
}

# Default backpressure limits per input format. Applied only when the user has
# not set the corresponding option, to cap micro-batch size and avoid CPU spikes
# (and partition skew) while a query catches up on a backlog. Override per node
# via input.options, or disable globally with
# global_settings.streaming_disable_backpressure_defaults = true.
STREAMING_BACKPRESSURE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    StreamingFormat.KAFKA.value: {"maxOffsetsPerTrigger": 1_000_000},
    StreamingFormat.FILE_STREAM.value: {"maxFilesPerTrigger": 1000},
    StreamingFormat.DELTA_STREAM.value: {"maxFilesPerTrigger": 1000},
}

# Base interval used by the "adaptive" trigger when no historical metrics are
# available yet. Overridable via global_settings.streaming_adaptive_base_interval.
DEFAULT_ADAPTIVE_BASE_INTERVAL = "5 seconds"

# Format-specific validations
STREAMING_VALIDATIONS = {
    "min_trigger_interval_seconds": 1,
    "max_watermark_delay_minutes": 60,
    "mutually_exclusive_kafka_options": [["subscribe", "subscribePattern", "assign"]],
}
