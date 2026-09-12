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


class SupportedFormats(Enum):
    """Supported data formats."""

    PARQUET = "parquet"
    JSON = "json"
    CSV = "csv"
    DELTA = "delta"
    PICKLE = "pickle"
    AVRO = "avro"
    ORC = "orc"
    XML = "xml"
    QUERY = "query"
    UNITY_CATALOG = "unity_catalog"


class WriteMode(Enum):
    """Supported write modes."""

    OVERWRITE = "overwrite"
    APPEND = "append"
    IGNORE = "ignore"
    ERROR = "error"


class ExecutionMode(Enum):
    """Execution modes."""

    LOCAL = "local"
    DISTRIBUTED = "distributed"


DEFAULT_CSV_OPTIONS = {"header": "true"}
DEFAULT_VACUUM_RETENTION_HOURS = 168  # 7 days
MIN_VACUUM_RETENTION_HOURS = 168  # Delta Lake enforced minimum
DEFAULT_ENCODING = "UTF-8"  # Default encoding for text file operations

CLOUD_URI_PREFIXES = ("s3://", "abfss://", "gs://", "dbfs:/")


def is_cloud_path(path: str) -> bool:
    """Check if a path uses a supported cloud storage prefix."""
    return any(str(path).startswith(prefix) for prefix in CLOUD_URI_PREFIXES)
