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
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from loguru import logger


@dataclass
class DataFingerprint:
    """Fingerprint of a dataset for lineage tracking."""

    input_key: str
    filepath: str
    file_size_bytes: Optional[int] = None
    file_mtime: Optional[str] = None
    schema_hash: Optional[str] = None
    columns: Optional[Dict[str, str]] = None
    row_count: Optional[int] = None
    sample_hash: Optional[str] = None
    # Raw file-byte hash, kept as metadata only. Unlike `fingerprint` (the field
    # fingerprint_policy compares), this is sensitive to physical row order —
    # a reordered re-export with identical content would flag a false positive
    # if used as the primary drift signal, so it never drives the policy.
    raw_file_hash: Optional[str] = None
    fingerprint: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_file_and_df(
        cls, input_key: str, filepath: str, df: Any, sample_rows: int = 100, mode: str = "fast"
    ) -> "DataFingerprint":
        """Compute fingerprint from file metadata + DataFrame structure."""
        fp = cls(input_key=input_key, filepath=filepath)
        fp._capture_file_stat(filepath)
        fp._capture_schema(df)
        if mode == "full":
            fp.raw_file_hash = fp._compute_full_file_hash(filepath)
            if hasattr(df, "shape"):
                fp.row_count = df.shape[0]
            fp.fingerprint = fp._compute_full_dataframe_hash(df)
        else:
            fp._capture_sample(df, sample_rows)
            fp._compute_combined_hash()
        return fp

    def _compute_full_file_hash(self, filepath: str) -> str:
        if not os.path.exists(filepath):
            return ""
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _compute_full_dataframe_hash(self, df: Any) -> str:
        """Hash the entire DataFrame's content — "full" mode's ground-truth
        check. Immune to the false positives a raw file-byte hash would produce
        on a re-export with reordered rows but identical content, and (via
        index reset) to the index-label sensitivity `_capture_sample` also
        guards against."""
        try:
            if hasattr(df, "reset_index") and hasattr(df, "to_json"):
                content_str = df.reset_index(drop=True).to_json()
            else:
                content_str = str(df)
        except Exception as e:
            logger.debug(f"Failed to hash full DataFrame content: {e}")
            content_str = str(df)
        return hashlib.sha256(content_str.encode()).hexdigest()

    def _capture_file_stat(self, filepath: str) -> None:
        try:
            if os.path.exists(filepath):
                stat = os.stat(filepath)
                self.file_size_bytes = stat.st_size
                self.file_mtime = str(stat.st_mtime)
        except Exception as e:
            logger.debug(f"Failed to stat {filepath}: {e}")

    def _capture_schema(self, df: Any) -> None:
        try:
            # Handle pandas/polars DataFrames
            if hasattr(df, "dtypes"):
                if isinstance(df.dtypes, dict):
                    columns = {str(k): str(v) for k, v in df.dtypes.items()}
                else:
                    # pandas Series or List of dtypes
                    pairs = list(zip(getattr(df, "columns", []), df.dtypes))
                    columns = {str(col): str(dtype) for col, dtype in pairs}
                # sort_keys=True makes both branches order-independent and
                # byte-identical in format, unlike the previous list-of-tuples
                # serialization used only for the Series/list-of-dtypes branch.
                schema_str = json.dumps(dict(sorted(columns.items())), sort_keys=True)
                self.schema_hash = hashlib.sha256(schema_str.encode()).hexdigest()
                self.columns = columns
        except Exception as e:
            logger.debug(f"Failed to capture schema: {e}")

    def _capture_sample(self, df: Any, sample_rows: int) -> None:
        try:
            if hasattr(df, "shape"):
                self.row_count = df.shape[0]

            if hasattr(df, "head") and hasattr(df, "tail"):
                sample_df = self._systematic_sample(df, sample_rows)
                # Index labels aren't part of the data being fingerprinted —
                # without resetting, two DataFrames with identical values but
                # a different index would hash differently (false drift positive).
                if hasattr(sample_df, "reset_index"):
                    sample_df = sample_df.reset_index(drop=True)
                # Simple string representation for hashing
                if hasattr(sample_df, "to_json"):
                    try:
                        sample_str = sample_df.to_json()
                    except Exception:
                        sample_str = str(sample_df)
                else:
                    sample_str = str(sample_df)
                self.sample_hash = hashlib.sha256(sample_str.encode()).hexdigest()
        except Exception as e:
            logger.debug(f"Failed to capture sample: {e}")

    @staticmethod
    def _systematic_sample(df: Any, sample_rows: int) -> Any:
        """Head + tail + evenly-spaced middle rows, budget split three ways.

        A plain ``df.head(sample_rows)`` is blind to any change concentrated
        past the sample window (e.g. rows appended or corrupted at the tail —
        a common real scenario for a dataset larger than the sample). Covering
        head, tail, and a systematic middle stride catches far more of those
        cases for the same O(sample_rows) cost.
        """
        n = len(df) if hasattr(df, "__len__") else None
        if not n or n <= sample_rows:
            return df.head(sample_rows)

        budget = max(1, sample_rows // 3)
        head = df.head(budget)
        tail = df.tail(budget)
        middle = df.iloc[budget:-budget] if n > 2 * budget else df.iloc[0:0]
        if len(middle) > 0:
            stride = max(1, len(middle) // budget)
            middle = middle.iloc[::stride].head(budget)

        import pandas as pd  # local import: fingerprint.py has no hard pandas dependency

        if isinstance(head, pd.DataFrame):
            return pd.concat([head, middle, tail])
        return df.head(sample_rows)

    def _compute_combined_hash(self) -> None:
        # file_mtime is captured as metadata but deliberately excluded: re-saving
        # identical data changes mtime and would flag a false data change under
        # fingerprint_policy=warn/fail.
        parts = [
            str(self.file_size_bytes),
            str(self.schema_hash),
            str(self.row_count),
            str(self.sample_hash),
        ]
        combined = "|".join(parts)
        self.fingerprint = hashlib.sha256(combined.encode()).hexdigest()
