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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from loguru import logger

ALGO_SPARK_EXACT = "xxhash64-multiset/v2"
ALGO_SPARK_EXACT_CRYPTO = "sha256-multiset/v3"
ALGO_SPARK_SAMPLE = "spark-minhash/v3"
ALGO_PANDAS_EXACT = "pandas-sha256/v2"
ALGO_PANDAS_SAMPLE = "pandas-systematic/v2"
ALGO_SCHEMA_ONLY = "schema-only/v2"
ALGO_LEGACY = "legacy/v1"
VALID_MODES = ("exact", "exact_crypto", "sample", "schema")
_FULL_SCAN_MODES = frozenset({"exact", "exact_crypto"})
_LEGACY_MODES = {"fast": "sample", "full": "exact", "exact-crypto": "exact_crypto"}


def normalize_mode(mode: Optional[str]) -> str:
    """Coerce a configured ``fingerprint_mode`` to one of :data:`VALID_MODES`."""
    raw = (mode or "exact").strip().lower()
    if raw in _LEGACY_MODES:
        new = _LEGACY_MODES[raw]
        logger.warning(
            "fingerprint_mode='{old}' is deprecated; use '{new}'. Note that "
            "'full' measured only the schema on Spark — '{new}' is stronger, not "
            "equivalent.",
            old=raw,
            new=new,
        )
        return new
    if raw not in VALID_MODES:
        logger.warning(
            "Unknown fingerprint_mode '{mode}'; falling back to 'exact'. Valid: {valid}",
            mode=raw,
            valid=", ".join(VALID_MODES),
        )
        return "exact"
    return raw


def detect_engine(df: Any) -> str:
    """Return ``"spark"``, ``"pandas"`` or ``"unknown"`` for *df*."""
    mod = type(df).__module__
    if "pyspark" in mod:
        return "spark"
    if "pandas" in mod:
        return "pandas"
    if hasattr(df, "rdd"):
        return "spark"
    if hasattr(df, "iloc"):
        return "pandas"
    return "unknown"


class FingerprintError(RuntimeError):
    """Raised when a fingerprint could not be computed as requested."""


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
    raw_file_hash: Optional[str] = None
    engine: str = "unknown"
    algorithm: str = ALGO_LEGACY
    mode: str = "exact"
    content_hash: Optional[str] = None
    degraded_reason: Optional[str] = None
    fingerprint: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_file_and_df(
        cls,
        input_key: str,
        filepath: str,
        df: Any,
        sample_rows: int = 100,
        mode: str = "exact",
    ) -> "DataFingerprint":
        """Compute a fingerprint from file metadata + DataFrame content."""
        mode = normalize_mode(mode)
        fp = cls(input_key=input_key, filepath=filepath, mode=mode)
        fp.engine = detect_engine(df)
        fp._capture_file_stat(filepath)
        fp._capture_schema(df)
        if mode in _FULL_SCAN_MODES:
            fp.raw_file_hash = fp._compute_full_file_hash(filepath)

        if fp.engine == "spark":
            fp._compute_spark(df, sample_rows)
        elif fp.engine == "pandas":
            fp._compute_pandas(df, sample_rows)
        else:
            fp.algorithm = ALGO_SCHEMA_ONLY
            fp.degraded_reason = f"unsupported dataframe type {type(df).__name__}"
            logger.warning(
                "Fingerprint for '{key}' degraded to schema-only: {reason}",
                key=input_key,
                reason=fp.degraded_reason,
            )

        fp._compute_combined_hash()
        return fp

    # ── Spark ────────────────────────────────────────────────────────────────

    def _compute_spark(self, df: Any, sample_rows: int) -> None:
        from pyspark.sql import functions as F  # type: ignore

        self.row_count = df.count()

        if self.mode == "schema":
            self.algorithm = ALGO_SCHEMA_ONLY
            return

        columns = [F.col(c) for c in df.columns]
        if not columns:
            self.algorithm = ALGO_SCHEMA_ONLY
            self.degraded_reason = "dataframe has no columns"
            return

        if self.mode == "sample":
            hashed = df.select(F.xxhash64(*columns).alias("_ducta_h"))
            rows = hashed.orderBy(F.col("_ducta_h").asc()).limit(sample_rows).collect()
            self.sample_hash = hashlib.sha256(
                "\n".join(str(r["_ducta_h"]) for r in rows).encode()
            ).hexdigest()
            self.content_hash = self.sample_hash
            self.algorithm = ALGO_SPARK_SAMPLE
            self.details["sample_rows_covered"] = len(rows)
            self.details["sampling"] = "deterministic-min-rowhash"
            return

        if self.mode == "exact_crypto":
            self._compute_spark_exact_crypto(df, columns)
            return

        row_hash = F.xxhash64(*columns)
        agg = (
            df.select(row_hash.alias("_ducta_h"))
            .agg(
                F.count("*").alias("n"),
                F.sum(F.col("_ducta_h").cast("decimal(38,0)")).alias("s"),
                F.bit_xor("_ducta_h").alias("x"),
            )
            .first()
        )
        n = int(agg["n"] or 0)
        s = int(agg["s"] or 0)
        x = int(agg["x"] or 0)
        self.content_hash = hashlib.sha256(f"{n}:{s}:{x}".encode()).hexdigest()
        self.algorithm = ALGO_SPARK_EXACT

    def _compute_spark_exact_crypto(self, df: Any, columns: list) -> None:
        """Order-independent digest built on SHA-256 rather than xxhash64."""
        from pyspark.sql import functions as F  # type: ignore

        parts = []
        for col in columns:
            as_str = col.cast("string")
            parts.append(
                F.when(as_str.isNull(), F.lit("\u0000N")).otherwise(
                    F.concat(F.length(as_str).cast("string"), F.lit(":"), as_str)
                )
            )
        row_hash = F.sha2(F.concat_ws("\u0001", *parts), 256)
        hashed = df.select(row_hash.alias("_ducta_h"))
        lane_a = F.conv(F.substring(F.col("_ducta_h"), 1, 16), 16, 10).cast("decimal(38,0)")
        lane_b = F.conv(F.substring(F.col("_ducta_h"), 17, 16), 16, 10).cast("decimal(38,0)")
        agg = hashed.agg(
            F.count("*").alias("n"),
            F.sum(lane_a).alias("a"),
            F.sum(lane_b).alias("b"),
        ).first()
        n = int(agg["n"] or 0)
        a = int(agg["a"] or 0)
        b = int(agg["b"] or 0)
        self.content_hash = hashlib.sha256(f"{n}:{a}:{b}".encode()).hexdigest()
        self.algorithm = ALGO_SPARK_EXACT_CRYPTO

    # ── pandas ───────────────────────────────────────────────────────────────

    def _compute_pandas(self, df: Any, sample_rows: int) -> None:
        self.row_count = int(df.shape[0])

        if self.mode == "schema":
            self.algorithm = ALGO_SCHEMA_ONLY
            return

        if self.mode in _FULL_SCAN_MODES:
            self.content_hash = self._pandas_content_hash(df)
            self.algorithm = ALGO_PANDAS_EXACT
            return

        self._capture_sample(df, sample_rows)
        self.content_hash = self.sample_hash
        self.algorithm = ALGO_PANDAS_SAMPLE
        self.details["sample_rows_covered"] = min(sample_rows, self.row_count)
        self.details["sampling"] = "head+middle+tail"

    @staticmethod
    def _pandas_content_hash(df: Any) -> str:
        """Hash the whole frame's content, insensitive to row order and index."""
        try:
            import pandas as pd  # local import: no hard pandas dependency here

            hashed = pd.util.hash_pandas_object(df, index=False)
            digest = hashlib.sha256()
            for value in sorted(int(v) for v in hashed):
                digest.update(str(value).encode())
            digest.update(f"|n={len(df)}".encode())
            return digest.hexdigest()
        except Exception as exc:  # noqa: BLE001 — fall back, but say so
            logger.debug("pandas content hash fell back to JSON: {}", exc)
            frame = df.reset_index(drop=True) if hasattr(df, "reset_index") else df
            content = frame.to_json() if hasattr(frame, "to_json") else str(frame)
            return hashlib.sha256(content.encode()).hexdigest()

    # ── Shared ───────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_full_file_hash(filepath: str) -> Optional[str]:
        """SHA-256 over the file's bytes, or None when there is no single file."""
        try:
            if not filepath or not os.path.isfile(filepath):
                return None
            hasher = hashlib.sha256()
            with open(filepath, "rb") as handle:
                for chunk in iter(lambda: handle.read(4096 * 1024), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except OSError as exc:
            logger.debug("Could not hash file bytes for {}: {}", filepath, exc)
            return None

    @staticmethod
    def _total_size_bytes(filepath: str) -> Optional[int]:
        """Bytes on disk for a dataset, whether it is one file or a directory."""
        path = Path(filepath)
        try:
            if path.is_file():
                return path.stat().st_size
            if path.is_dir():
                return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        except OSError as e:
            logger.debug(f"Could not size {filepath}: {e}")
        return None

    def _capture_file_stat(self, filepath: str) -> None:
        try:
            if os.path.exists(filepath):
                stat = os.stat(filepath)
                self.file_size_bytes = self._total_size_bytes(filepath)
                self.file_mtime = str(stat.st_mtime)
        except Exception as e:
            logger.debug(f"Failed to stat {filepath}: {e}")

    def _capture_schema(self, df: Any) -> None:
        try:
            columns = self._schema_columns(df)
            if not columns:
                return

            schema_str = json.dumps(dict(sorted(columns.items())), sort_keys=True)
            self.schema_hash = hashlib.sha256(schema_str.encode()).hexdigest()
            self.columns = columns
        except Exception as e:
            logger.debug(f"Failed to capture schema: {e}")

    @staticmethod
    def _schema_columns(df: Any) -> Dict[str, str]:
        """``{column: dtype}`` for Spark, pandas or polars."""
        dtypes = getattr(df, "dtypes", None)
        if dtypes is None:
            return {}
        if isinstance(dtypes, dict):
            return {str(k): str(v) for k, v in dtypes.items()}
        pairs = list(dtypes)
        if pairs and isinstance(pairs[0], tuple) and len(pairs[0]) == 2:
            return {str(name): str(dtype) for name, dtype in pairs}
        return {str(col): str(dtype) for col, dtype in zip(getattr(df, "columns", []), pairs)}

    def _capture_sample(self, df: Any, sample_rows: int) -> None:
        try:
            sample_df = self._systematic_sample(df, sample_rows)
            if hasattr(sample_df, "reset_index"):
                sample_df = sample_df.reset_index(drop=True)
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
        """Head + tail + evenly-spaced middle rows, budget split three ways."""
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
        parts = [
            self.algorithm,
            str(self.schema_hash),
            str(self.row_count),
            str(self.content_hash),
        ]
        combined = "|".join(parts)
        self.fingerprint = hashlib.sha256(combined.encode()).hexdigest()


def comparable(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Whether two serialized fingerprints may be compared, and why not."""
    algo_a = a.get("algorithm") or ALGO_LEGACY
    algo_b = b.get("algorithm") or ALGO_LEGACY
    if algo_a != algo_b:
        return False, f"algorithm differs: {algo_a} vs {algo_b}"

    engine_a = a.get("engine") or "unknown"
    engine_b = b.get("engine") or "unknown"
    if engine_a != engine_b:
        return False, f"engine differs: {engine_a} vs {engine_b}"

    if algo_a == ALGO_SCHEMA_ONLY:
        return False, "schema-only fingerprints carry no content evidence"

    return True, None
