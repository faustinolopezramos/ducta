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

File-based run store: one directory per execution on the local filesystem.

This is the persistence layer that keeps the optional SQLite store *disposable*.
Every run gets:

    <runs_dir>/<execution_id>/
        meta.json     # execution metadata (status, exit_code, duration, timestamps)
        logs.jsonl    # one LogEntry as JSON per line, append-only

It works regardless of ``DATABASE_URL`` (even in pure in-memory mode), so deleting
``executions.db`` never loses anything irrecoverable: configuration lives in Git and
run history stays inspectable on disk with ``cat`` / ``jq``.

All disk operations are best-effort: failures are logged but never raised into the
execution hot path.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, List, Optional, TextIO

from loguru import logger

from ducta.api.models.execution import ExecutionResponse, LogEntry
from ducta.api.utils.fsio import atomic_write_json

_META_FILENAME = "meta.json"
_LOGS_FILENAME = "logs.jsonl"


class FileLogStore:
    """Append-only, thread-safe run store backed by the filesystem."""

    # Flush to disk every N appends per execution instead of on every single
    # line -- verbose pipelines were doing a blocking fsync per log line while
    # holding the execution-body lock upstream (runner.py::_stdout_capture_lock).
    _FLUSH_EVERY = 20

    def __init__(self, base_dir: str) -> None:
        self._base = Path(base_dir).expanduser()
        self._lock = threading.RLock()
        self._handles: Dict[str, TextIO] = {}
        self._pending_flush_count: Dict[str, int] = {}

    # ── Paths ─────────────────────────────────────────────────────────────────

    def _run_dir(self, execution_id: str) -> Path:
        return self._base / execution_id

    @staticmethod
    def _is_safe_id(execution_id: str) -> bool:
        """Reject anything that is not a plain run id.

        Writes only ever use ids this process generated, but the read methods
        below are reached from ``GET /executions/{execution_id}/logs`` — the id
        is caller-supplied there, and `self._base / execution_id` would happily
        walk out of the runs directory given `../..`.
        """
        return bool(execution_id) and all(c.isalnum() or c in "-_" for c in execution_id)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start_run(self, record: ExecutionResponse) -> None:
        """Create the run directory, write the initial meta.json and open logs.jsonl."""
        try:
            run_dir = self._run_dir(record.id)
            run_dir.mkdir(parents=True, exist_ok=True)
            self._write_meta(record)
            with self._lock:
                if record.id not in self._handles:
                    self._handles[record.id] = (run_dir / _LOGS_FILENAME).open(
                        "a", encoding="utf-8"
                    )
        except OSError as exc:  # noqa: BLE001
            logger.warning("FileLogStore.start_run failed for {id}: {exc}", id=record.id, exc=exc)

    def append(self, execution_id: str, entry: LogEntry) -> None:
        """Append a single log entry as a JSON line.

        Flushed to disk every `_FLUSH_EVERY` lines rather than on every write
        (see `finish_run`/`cleanup_all` for the unconditional flush on close).
        No-op if the run is not open.
        """
        try:
            with self._lock:
                handle = self._handles.get(execution_id)
                if handle is None:
                    return
                handle.write(entry.model_dump_json() + "\n")
                pending = self._pending_flush_count.get(execution_id, 0) + 1
                if pending >= self._FLUSH_EVERY:
                    handle.flush()
                    pending = 0
                self._pending_flush_count[execution_id] = pending
        except (OSError, ValueError) as exc:  # noqa: BLE001
            logger.warning("FileLogStore.append failed for {id}: {exc}", id=execution_id, exc=exc)

    def finish_run(self, record: ExecutionResponse) -> None:
        """Rewrite meta.json with terminal state, sync to StorageBackend, and close logs handle."""
        try:
            self._write_meta(record)
        finally:
            with self._lock:
                handle = self._handles.pop(record.id, None)
                self._pending_flush_count.pop(record.id, None)
            if handle is not None:
                try:
                    handle.flush()
                    handle.close()
                except OSError:  # noqa: BLE001
                    pass
            # Sync logs and meta to active StorageBackend (S3/Local)
            try:
                from ducta.core.storage import get_storage_backend

                storage = get_storage_backend()
                meta_path = self._run_dir(record.id) / _META_FILENAME
                logs_path = self._run_dir(record.id) / _LOGS_FILENAME
                if meta_path.is_file():
                    storage.put_object(f"runs/{record.id}/meta.json", meta_path.read_bytes())
                if logs_path.is_file():
                    storage.put_object(f"runs/{record.id}/logs.jsonl", logs_path.read_bytes())
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "StorageBackend sync failed for run {id}: {exc}", id=record.id, exc=exc
                )

    def cleanup_all(self) -> None:
        """Close any open handles (on shutdown)."""
        with self._lock:
            handles = list(self._handles.values())
            self._handles.clear()
            self._pending_flush_count.clear()
        for handle in handles:
            try:
                handle.flush()
                handle.close()
            except OSError:  # noqa: BLE001
                pass

    # ── Reading ───────────────────────────────────────────────────────────────
    #
    # Without these the store was write-only: every run was faithfully recorded
    # to disk and nothing in the application could ever read it back, so a
    # restart (or the six-hour in-memory retention) lost the history the
    # `runs_dir` setting promises to keep "inspectable on disk".

    def _flush_if_open(self, execution_id: str) -> None:
        """Push buffered lines to disk so a live run reads back complete.

        `append` only flushes every `_FLUSH_EVERY` lines, so without this a read
        of a running execution silently truncates the last few entries.
        """
        with self._lock:
            handle = self._handles.get(execution_id)
            if handle is None:
                return
            try:
                handle.flush()
                self._pending_flush_count[execution_id] = 0
            except OSError:  # noqa: BLE001
                pass

    def read_meta(self, execution_id: str) -> Optional[ExecutionResponse]:
        """Return the persisted execution record, or None when absent/unreadable."""
        if not self._is_safe_id(execution_id):
            return None
        meta_path = self._run_dir(execution_id) / _META_FILENAME
        try:
            if not meta_path.is_file():
                return None
            return ExecutionResponse.model_validate_json(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # noqa: BLE001
            logger.warning(
                "FileLogStore.read_meta failed for {id}: {exc}", id=execution_id, exc=exc
            )
            return None

    def read_logs(self, execution_id: str) -> List[LogEntry]:
        """Return every persisted log entry for a run, oldest first.

        A malformed line is skipped rather than failing the whole read: a run
        killed mid-write can leave a half-written final line, and losing one
        entry is better than losing the entire history behind it.
        """
        if not self._is_safe_id(execution_id):
            return []
        self._flush_if_open(execution_id)
        logs_path = self._run_dir(execution_id) / _LOGS_FILENAME
        entries: List[LogEntry] = []
        try:
            if not logs_path.is_file():
                return []
            with logs_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(LogEntry.model_validate_json(line))
                    except ValueError:
                        continue
        except OSError as exc:  # noqa: BLE001
            logger.warning(
                "FileLogStore.read_logs failed for {id}: {exc}", id=execution_id, exc=exc
            )
        return entries

    def list_runs(self, limit: int = 500) -> List[ExecutionResponse]:
        """Return persisted run records, newest first."""
        try:
            if not self._base.is_dir():
                return []
            candidates = [d for d in self._base.iterdir() if d.is_dir()]
        except OSError as exc:  # noqa: BLE001
            logger.warning("FileLogStore.list_runs failed: {exc}", exc=exc)
            return []

        # Order by mtime before parsing so a large runs_dir costs a stat per
        # directory rather than a full JSON parse per directory.
        def _mtime(d: Path) -> float:
            try:
                return (d / _META_FILENAME).stat().st_mtime
            except OSError:
                return 0.0

        candidates.sort(key=_mtime, reverse=True)
        records: List[ExecutionResponse] = []
        for run_dir in candidates[:limit]:
            record = self.read_meta(run_dir.name)
            if record is not None:
                records.append(record)
        return records

    # ── Internal ──────────────────────────────────────────────────────────────

    def _write_meta(self, record: ExecutionResponse) -> None:
        try:
            run_dir = self._run_dir(record.id)
            run_dir.mkdir(parents=True, exist_ok=True)
            meta_path = run_dir / _META_FILENAME
            atomic_write_json(meta_path, record.model_dump(mode="json"))
        except OSError as exc:  # noqa: BLE001
            logger.warning("FileLogStore meta write failed for {id}: {exc}", id=record.id, exc=exc)


def build_file_log_store(runs_dir: str) -> Optional[FileLogStore]:
    """Return a FileLogStore, or None when file persistence is disabled.

    Disabled when *runs_dir* is empty/blank, mirroring the DATABASE_URL opt-out.
    """
    if not runs_dir or not runs_dir.strip():
        return None
    return FileLogStore(runs_dir.strip())
