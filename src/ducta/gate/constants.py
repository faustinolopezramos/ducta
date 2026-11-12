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


# The one definition, also ``ducta.setting.schemas.WriteMode``. It lives here because
# ``gate`` cannot import ``setting`` (``setting`` imports ``check``, which imports
# ``gate``). There were two copies, a plain ``Enum`` and a ``str`` one, and a mode
# handed from one side to the other turned into "WriteMode.OVERWRITE" under ``str()``.
# The docstring is the description editors show in the configuration's JSON Schema.
class WriteMode(str, Enum):
    """Write modes for outputs."""

    def __str__(self) -> str:
        # The value, so a mode goes into a path, a log or a JSON as is.
        return str(self.value)

    OVERWRITE = "overwrite"
    APPEND = "append"
    IGNORE = "ignore"
    ERROR = "error"
    #: Upsert by key (Delta only) — see ``DeltaWriter``.
    MERGE = "merge"


class ExecutionMode(Enum):
    """Execution modes. Mirrors ``ducta.setting.schemas.ExecutionMode`` (see ``WriteMode``)."""

    LOCAL = "local"
    DATABRICKS = "databricks"
    DISTRIBUTED = "distributed"


# RFC 4180: a quote inside a quoted value is doubled. Spark's own default escape is a
# backslash, which read back what a CSV writer wrote as different values.
DEFAULT_CSV_OPTIONS = {"header": "true", "quote": '"', "escape": '"'}
# A value may hold a line break; without multiLine it reads as two rows. The cost is that a
# file is no longer split: set `multiLine: false` on a large file known to have none.
CSV_READ_DEFAULTS = {**DEFAULT_CSV_OPTIONS, "multiLine": "true"}
# Spark trims values when it writes a CSV, and nothing says so.
CSV_WRITE_DEFAULTS = {
    **DEFAULT_CSV_OPTIONS,
    "ignoreLeadingWhiteSpace": "false",
    "ignoreTrailingWhiteSpace": "false",
}
DEFAULT_VACUUM_RETENTION_HOURS = 168  # 7 days
MIN_VACUUM_RETENTION_HOURS = 168  # Delta Lake enforced minimum
DEFAULT_ENCODING = "UTF-8"  # Default encoding for text file operations

#: Every storage scheme Ducta treats as remote: joined as text, never through ``Path``
#: (which folds ``s3a://bucket`` into ``s3a:/bucket``, a local folder). The one list:
#: gate, stream and the evidence directories all read it.
CLOUD_URI_PREFIXES = (
    "s3://",
    "s3a://",
    "s3n://",
    "gs://",
    "abfs://",
    "abfss://",
    "wasb://",
    "wasbs://",
    "hdfs://",
    "dbfs:/",
)


def is_cloud_path(path: str) -> bool:
    """Check if a path uses a supported cloud storage prefix."""
    return any(str(path).startswith(prefix) for prefix in CLOUD_URI_PREFIXES)


def join_cloud_path(*parts: str) -> str:
    """Join cloud storage paths properly (``Path`` would fold ``s3://`` into ``s3:/``)."""
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    if not cleaned:
        return ""
    head = cleaned[0]
    if "://" in head:
        scheme, rest = head.split("://", 1)
        head = scheme + "://" + rest.rstrip("/")
    else:
        head = head.rstrip("/")
    tail = [p.strip("/") for p in cleaned[1:] if p.strip("/")]
    return head + ("/" + "/".join(tail) if tail else "")


def join_path(base: str, *parts: str) -> str:
    """``base/part/...``: as text for a cloud URI, through ``Path`` for a local one."""
    if is_cloud_path(base):
        return join_cloud_path(base, *parts)
    from pathlib import Path

    return str(Path(base).joinpath(*parts))
