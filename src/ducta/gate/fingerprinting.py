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

from ducta.gate.context_manager import ContextManager


def compute_fingerprint(
    context_manager: ContextManager,
    *,
    key: str,
    identifier: str,
    dataframe: Any,
    sample_rows: Optional[int] = None,
    window: Optional[Dict[str, Any]] = None,
    delta: Optional[Dict[str, Any]] = None,
    mode: Optional[str] = None,
) -> Any:
    """Compute a DataFingerprint, reading fingerprint_mode/sample_rows from global_config.

    The default mode is ``auto``: cost proportional to what the run processed
    (a Delta commit version, an incremental window, or a dataset small enough
    to hash in full), never a full scan of a large table's whole history.
    """
    from ducta.mlrun.fingerprint import DataFingerprint  # optional dependency (mlrun)

    mode = mode or context_manager.get_nested("global_config.fingerprint_mode", None) or "auto"
    rows = (
        sample_rows
        if sample_rows is not None
        else context_manager.get_nested("global_config.fingerprint_sample_rows", 100)
    )
    max_bytes = context_manager.get_nested("global_config.fingerprint_exact_max_bytes", None)
    return DataFingerprint.from_file_and_df(
        key,
        identifier,
        dataframe,
        sample_rows=rows,
        mode=mode,
        window=window,
        delta=delta,
        exact_max_bytes=int(max_bytes) if max_bytes is not None else None,
    )


def _delta_table(spark: Any, source: str) -> Any:
    """A ``DeltaTable`` handle for a path or a catalog table name, or None.

    The Python API rather than ``DESCRIBE … delta.`<path>```: Delta's SQL path
    identifiers do not resolve relative paths, which is how local projects
    address their data.
    """
    from delta.tables import DeltaTable  # type: ignore

    if _looks_like_table_name(source):
        return DeltaTable.forName(spark, source)
    if not DeltaTable.isDeltaTable(spark, source):
        return None
    return DeltaTable.forPath(spark, source)


def delta_identity(spark: Any, source: str, pinned_version: Any = None) -> Optional[Dict[str, Any]]:
    """``{table_id, version, ...}`` of a Delta table, from its transaction log only.

    ``source`` is a path or a catalog table name. ``pinned_version`` is the
    ``versionAsOf`` the read used, when it used one — that, not the latest
    commit, is what the run read. Returns None when ``source`` is not a Delta
    table or the log cannot be read; the caller then falls back to hashing.
    """
    if spark is None or not source:
        return None
    try:
        table = _delta_table(spark, source)
        if table is None:
            return None
        detail = table.detail().first()
        if pinned_version is not None:
            version = int(pinned_version)
        else:
            version = int(table.history(1).first()["version"])
        return {
            "table_id": detail["id"],
            "version": version,
            "num_files": detail["numFiles"],
            "size_bytes": detail["sizeInBytes"],
        }
    except Exception:  # noqa: BLE001 — identity is an optimisation; hashing still works
        return None


def delta_last_operation(spark: Any, source: str) -> Optional[Dict[str, Any]]:
    """Version and ``operationMetrics`` of the latest commit (what a write just did)."""
    if spark is None or not source:
        return None
    try:
        table = _delta_table(spark, source)
        if table is None:
            return None
        row = table.history(1).first()
        metrics = row["operationMetrics"] or {}
        return {
            "version": int(row["version"]),
            "operation": row["operation"],
            "metrics": {k: str(v) for k, v in dict(metrics).items()},
        }
    except Exception:  # noqa: BLE001
        return None


def _looks_like_table_name(source: str) -> bool:
    return "/" not in source and ":" not in source and "\\" not in source


def diff_schema_columns(
    previous: Optional[Dict[str, str]], current: Optional[Dict[str, str]]
) -> Optional[str]:
    """Human-readable diff of column name/dtype dicts, or None if nothing changed
    (or either side lacks column-level detail — e.g. an older fingerprint predating
    this field, or a dataframe type where schema capture failed).
    """
    if not previous or not current:
        return None
    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    retyped = sorted(col for col in (set(previous) & set(current)) if previous[col] != current[col])
    if not (added or removed or retyped):
        return None
    parts = []
    if added:
        parts.append(f"added={added}")
    if removed:
        parts.append(f"removed={removed}")
    if retyped:
        parts.append(f"type_changed={retyped}")
    return "; ".join(parts)
