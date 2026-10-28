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

from ducta.gate.context_manager import ContextManager
from ducta.gate.exceptions import ReadOperationError


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


def check_fingerprint_policy(
    policy: str, previous: Dict[str, Any], data_fingerprint: Any, input_key: str
) -> None:
    """Compare an input's fingerprint with the previous successful run's.

    ``policy`` is ``warn`` (log it) or ``fail`` (raise ``ReadOperationError``); ``previous``
    is that input's recorded fingerprint (``{}`` when there is none). A fingerprint made by
    another engine or algorithm is not comparable and becomes the new baseline, silently.
    Anything unexpected while comparing skips the check: it never blocks a read by itself.
    """
    message = None
    try:
        previous_hash = previous.get("fingerprint")
        if not previous_hash or previous_hash == data_fingerprint.fingerprint:
            return

        from ducta.mlrun.fingerprint import comparable

        can_compare, why = comparable(previous, data_fingerprint.to_dict())
        if not can_compare:
            logger.info(
                "Skipping fingerprint_policy for '{}': the recorded fingerprint is "
                "not comparable to this run's ({}). This run's fingerprint becomes "
                "the new baseline.",
                input_key,
                why,
            )
            return

        message = (
            f"Input '{input_key}' changed since the previous successful run: "
            f"fingerprint {previous_hash[:12]}… → {data_fingerprint.fingerprint[:12]}… "
            f"(rows {previous.get('row_count')} → {data_fingerprint.row_count}, "
            f"mtime {previous.get('file_mtime')} → {data_fingerprint.file_mtime})"
        )
        column_diff = diff_schema_columns(
            previous.get("columns"), getattr(data_fingerprint, "columns", None)
        )
        if column_diff:
            message += f" | schema drift: {column_diff}"
    except Exception as error:  # noqa: BLE001 — see the docstring
        logger.debug("Fingerprint policy check skipped for '{}': {}", input_key, error)
        return

    if policy == "fail":
        raise ReadOperationError(
            f"{message}. Aborting because fingerprint_policy=fail. "
            "Re-run with fingerprint_policy=warn (or record) to accept the new data."
        )
    logger.warning("{}. Results may not be comparable to the previous run.", message)
