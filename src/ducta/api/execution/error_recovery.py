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

import enum
import json
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

_ERRORS_FILENAME = "errors.json"
# Retention: keep the most recent N executions' error logs on disk so a failed
# run stays diagnosable after the in-memory registry is cleaned up.
_MAX_ERROR_LOGS_KEPT = 50


class ErrorCategory(str, enum.Enum):
    TEMPORARY = "temporary"
    PERMANENT = "permanent"
    RESOURCE = "resource"
    CONFIGURATION = "configuration"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class RecoveryStrategy(str, enum.Enum):
    RETRY = "retry"
    SKIP_NODE = "skip_node"
    FALLBACK = "fallback"
    ABORT = "abort"
    MANUAL = "manual"


@dataclass
class ErrorContext:
    execution_id: str
    node_id: Optional[str] = None
    node_type: Optional[str] = None
    pipeline_name: Optional[str] = None
    attempt: int = 1
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    environment: Optional[str] = None
    user_id: Optional[str] = None


@dataclass
class RecoveryPlan:
    primary_strategy: RecoveryStrategy
    alternative_strategies: List[RecoveryStrategy] = field(default_factory=list)
    retry_delay_seconds: Optional[float] = None
    fallback_value: Optional[Any] = None
    abort_reason: Optional[str] = None
    notes: Optional[str] = None


class ErrorAnalyzer:
    CATEGORY_MAP = {
        TimeoutError: ErrorCategory.TIMEOUT,
        OSError: ErrorCategory.RESOURCE,
        MemoryError: ErrorCategory.RESOURCE,
        ImportError: ErrorCategory.CONFIGURATION,
        ValueError: ErrorCategory.PERMANENT,
        TypeError: ErrorCategory.PERMANENT,
        RuntimeError: ErrorCategory.TEMPORARY,
    }

    @staticmethod
    def categorize_error(exception: Exception) -> ErrorCategory:
        exc_type = type(exception)
        if exc_type in ErrorAnalyzer.CATEGORY_MAP:
            return ErrorAnalyzer.CATEGORY_MAP[exc_type]

        for parent_type, category in ErrorAnalyzer.CATEGORY_MAP.items():
            if isinstance(exception, parent_type):
                return category

        msg = str(exception).lower()
        if any(w in msg for w in ("timeout", "exceeded")):
            return ErrorCategory.TIMEOUT
        if any(w in msg for w in ("memory", "resource", "pool")):
            return ErrorCategory.RESOURCE
        if any(w in msg for w in ("config", "missing", "invalid")):
            return ErrorCategory.CONFIGURATION
        return ErrorCategory.UNKNOWN

    @staticmethod
    def recommend_recovery(
        exception: Exception,
        context: ErrorContext,
        attempt: int = 1,
        max_attempts: int = 3,
    ) -> RecoveryPlan:
        category = ErrorAnalyzer.categorize_error(exception)

        if category == ErrorCategory.TIMEOUT:
            return RecoveryPlan(
                primary_strategy=RecoveryStrategy.ABORT,
                abort_reason="Pipeline execution exceeded timeout",
                notes="Consider increasing execution timeout or optimizing pipeline",
            )

        if category == ErrorCategory.RESOURCE:
            return RecoveryPlan(
                primary_strategy=(
                    RecoveryStrategy.RETRY if attempt < max_attempts else RecoveryStrategy.ABORT
                ),
                alternative_strategies=[RecoveryStrategy.SKIP_NODE],
                retry_delay_seconds=5 * (2 ** (attempt - 1)),
                abort_reason="Resource exhaustion" if attempt >= max_attempts else None,
                notes="Consider reducing parallelism or chunk size",
            )

        if category == ErrorCategory.CONFIGURATION:
            return RecoveryPlan(
                primary_strategy=RecoveryStrategy.ABORT,
                abort_reason="Configuration error - manual intervention required",
                notes="Review pipeline configuration and fix issues",
            )

        if category == ErrorCategory.PERMANENT:
            return RecoveryPlan(
                primary_strategy=RecoveryStrategy.ABORT,
                abort_reason="Permanent error - will not succeed on retry",
                notes=f"Error: {str(exception)[:100]}",
            )

        return RecoveryPlan(
            primary_strategy=(
                RecoveryStrategy.RETRY if attempt < max_attempts else RecoveryStrategy.ABORT
            ),
            alternative_strategies=[RecoveryStrategy.SKIP_NODE],
            retry_delay_seconds=1 * (2 ** (attempt - 1)),
            abort_reason="Max retry attempts exceeded" if attempt >= max_attempts else None,
        )

    @staticmethod
    def get_error_details(exception: Exception) -> Dict[str, Any]:
        tb_lines = traceback.format_exception(type(exception), exception, exception.__traceback__)
        return {
            "type": type(exception).__name__,
            "message": str(exception),
            "category": ErrorAnalyzer.categorize_error(exception).value,
            "traceback": "".join(tb_lines),
            "traceback_lines": tb_lines[-10:],
        }


class ExecutionErrorLog:
    def __init__(self, execution_id: str, base_dir: Optional[str] = None):
        self.execution_id = execution_id
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.start_time = datetime.now(tz=timezone.utc)
        # When set, `save()` mirrors the log to <base_dir>/<execution_id>/errors.json
        # so failures survive the in-memory registry cleanup (and server restarts).
        self._base_dir = base_dir

    def log_error(
        self,
        exception: Exception,
        context: ErrorContext,
        recovery_plan: Optional[RecoveryPlan] = None,
    ) -> None:
        error_details = ErrorAnalyzer.get_error_details(exception)
        if recovery_plan is None:
            recovery_plan = ErrorAnalyzer.recommend_recovery(exception, context)
        plan_dict = {
            "primary": recovery_plan.primary_strategy.value,
            "alternatives": [s.value for s in recovery_plan.alternative_strategies],
            "retry_delay": recovery_plan.retry_delay_seconds,
            "notes": recovery_plan.notes,
        }

        self.errors.append(
            {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "execution_id": self.execution_id,
                "node_id": context.node_id,
                "node_type": context.node_type,
                "attempt": context.attempt,
                "error": error_details,
                "recovery_plan": plan_dict,
            }
        )

        logger.error(
            "Execution {exec_id}: Node {node_id} failed (attempt {attempt}): {error_type}: {msg}",
            exec_id=self.execution_id,
            node_id=context.node_id,
            attempt=context.attempt,
            error_type=type(exception).__name__,
            msg=str(exception)[:80],
        )

    def log_warning(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self.warnings.append(
            {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "execution_id": self.execution_id,
                "message": message,
                "context": context or {},
            }
        )
        logger.warning("Execution {exec_id}: {msg}", exec_id=self.execution_id, msg=message)

    def get_summary(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "elapsed_seconds": (datetime.now(tz=timezone.utc) - self.start_time).total_seconds(),
            "errors": self.errors,
            "warnings": self.warnings,
            "has_critical_errors": any(
                err["error"]["category"] == "permanent" for err in self.errors
            ),
        }

    def is_recoverable(self) -> bool:
        for error in self.errors:
            if error["error"]["category"] in ("permanent", "timeout"):
                return False
        return len(self.errors) < 10

    # ── Disk persistence (best-effort, mirrors FileLogStore semantics) ────────

    def save(self) -> None:
        """Atomically mirror the log to <base_dir>/<execution_id>/errors.json.

        No-op when file persistence is disabled or the log has nothing to store.
        Failures are logged but never raised into the execution hot path.
        """
        if not self._base_dir:
            return
        if not self.errors and not self.warnings:
            return
        try:
            run_dir = Path(self._base_dir) / self.execution_id
            run_dir.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self.get_summary(), indent=2, ensure_ascii=False, default=str)
            tmp_path = run_dir / f"{_ERRORS_FILENAME}.tmp"
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(run_dir / _ERRORS_FILENAME)
        except OSError as exc:  # noqa: BLE001
            logger.warning(
                "ExecutionErrorLog.save failed for {id}: {exc}", id=self.execution_id, exc=exc
            )

    @staticmethod
    def load_from_disk(execution_id: str, base_dir: Optional[str]) -> Optional[Dict[str, Any]]:
        """Return the persisted summary dict for an execution, or None."""
        if not base_dir:
            return None
        try:
            path = Path(base_dir) / execution_id / _ERRORS_FILENAME
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # noqa: BLE001
            logger.warning(
                "ExecutionErrorLog.load failed for {id}: {exc}", id=execution_id, exc=exc
            )
            return None


_error_logs: Dict[str, ExecutionErrorLog] = {}
# Multiple concurrent pipeline executions (each in its own thread) call
# get_error_log/flush_error_log for their own execution_id — same locking
# pattern already used for resilience_core.py's equivalent module-level
# registry (_resilience_contexts/_resilience_lock).
_error_logs_lock = threading.Lock()


def _error_base_dir() -> Optional[str]:
    """Resolve the runs dir configured for file persistence (empty → disabled)."""
    try:
        from ducta.api.config import get_settings

        runs_dir = get_settings().runs_dir
        return runs_dir.strip() if runs_dir and runs_dir.strip() else None
    except Exception:  # noqa: BLE001
        return None


def get_error_log(execution_id: str) -> ExecutionErrorLog:
    with _error_logs_lock:
        if execution_id not in _error_logs:
            _error_logs[execution_id] = ExecutionErrorLog(execution_id, base_dir=_error_base_dir())
        return _error_logs[execution_id]


def try_get_error_log(execution_id: str) -> Optional[ExecutionErrorLog]:
    """Return the in-memory log without creating one."""
    with _error_logs_lock:
        return _error_logs.get(execution_id)


def _prune_error_logs(max_keep: int = _MAX_ERROR_LOGS_KEPT) -> None:
    """Keep only the most recent `max_keep` persisted error logs on disk."""
    base_dir = _error_base_dir()
    if not base_dir:
        return
    try:
        root = Path(base_dir)
        persisted = sorted(
            root.glob(f"*/{_ERRORS_FILENAME}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in persisted[max_keep:]:
            stale.unlink(missing_ok=True)
    except OSError as exc:  # noqa: BLE001
        logger.debug("Error log pruning failed: {exc}", exc=exc)


def flush_error_log(execution_id: str) -> bool:
    """Persist the in-memory log to disk (if any) and drop it from memory.

    Returns True when an entry existed. Callers use this when a run finishes:
    the file keeps the failure diagnosable after the in-memory registry is
    cleaned up, and `load_error_log_summary` reads it back for the API.
    """
    with _error_logs_lock:
        log = _error_logs.pop(execution_id, None)
    if log is not None:
        log.save()
        _prune_error_logs()
        return True
    return False


def delete_error_log(execution_id: str) -> bool:
    """Alias kept for compatibility: flush-then-drop (persists to disk first)."""
    return flush_error_log(execution_id)


def load_error_log_summary(execution_id: str) -> Optional[Dict[str, Any]]:
    """Return the error summary for an execution, from memory or disk.

    Prefers the live in-memory log (so a running execution's errors are served
    immediately); falls back to the persisted file after cleanup/restart.
    """
    log = try_get_error_log(execution_id)
    if log is not None and (log.errors or log.warnings):
        return log.get_summary()
    return ExecutionErrorLog.load_from_disk(execution_id, _error_base_dir())
