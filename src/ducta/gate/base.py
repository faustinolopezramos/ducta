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

from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.gate.constants import is_cloud_path
from ducta.gate.context_manager import ContextManager
from ducta.gate.exceptions import ConfigurationError, IOManagerError
from ducta.gate.sql import SQLSanitizer
from ducta.gate.validators import ConfigValidator


class BaseIO:
    """Base class for input/output operations with enhanced validation and error handling."""

    def __init__(self, context: Any):
        """Initialize BaseIO with application context (dict or object)."""
        if context is None:
            raise ConfigurationError("Context cannot be None") from None
        self.config_validator = ConfigValidator()
        self._context = context
        self.context_manager = ContextManager(context)
        logger.debug("BaseIO initialized with context")

    @property
    def context(self) -> Any:
        """Current application context (dict or object)."""
        return self._context

    @context.setter
    def context(self, value: Any) -> None:
        """Set context and keep the internal ContextManager in sync."""
        if value is None:
            raise ConfigurationError("Context cannot be None") from None
        self._context = value
        self.context_manager = ContextManager(value)

    def _ctx_get(self, key: str, default: Optional[Any] = None) -> Any:
        """Safe get from context for both dict and object."""
        return self.context_manager.get(key, default)

    def _ctx_spark(self) -> Optional[Any]:
        """Get SparkSession if present, else None."""
        return self.context_manager.get_spark()

    def _get_execution_mode(self) -> Optional[str]:
        """Get normalized execution mode from context."""
        return self.context_manager.get_execution_mode()

    def _is_local(self) -> bool:
        """Check if execution mode is local."""
        return self.context_manager.is_local_mode()

    def _spark_available(self) -> bool:
        """Check if Spark context is available."""
        return self.context_manager.is_spark_available()

    def _prepare_local_directory(self, path: str) -> None:
        """Create local directories if necessary for local filesystem paths."""
        if "://" in path or is_cloud_path(path):
            logger.debug("Skipping local directory creation for non-local path: {}", path)
            return

        path_obj = Path(path)
        dir_path = (
            path_obj if (path_obj.suffix == "" or path.endswith(("/", "\\"))) else path_obj.parent
        )

        if dir_path and not dir_path.exists():
            try:
                logger.debug("Creating directory: {}", dir_path)
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.info("Directory created: {}", dir_path)
            except OSError as error:
                logger.exception("Error creating local directory for path: {}", path)
                raise IOManagerError(
                    f"Failed to create directory for path {path}: {error}"
                ) from error

    @staticmethod
    def sanitize_sql_query(query: str) -> str:
        """Safe sanitization of SQL queries using the specialized class."""
        return SQLSanitizer.sanitize_query(query)

    def _record_fingerprint(
        self,
        scope: str,
        key: str,
        identifier: str,
        dataframe: Any,
        sample_rows: Optional[int] = None,
        extra_details: Optional[Dict[str, Any]] = None,
        **options: Any,
    ) -> Optional[Any]:
        """Compute (if enabled) and store a DataFingerprint under ``_{scope}_fingerprints``.

        ``options`` (``window``, ``delta``, ``mode``) pass through to
        :func:`ducta.gate.fingerprinting.compute_fingerprint`.
        """
        if not self.context_manager.get_nested("global_config.enable_data_fingerprinting", True):
            return None
        try:
            from ducta.gate.fingerprinting import compute_fingerprint

            fingerprint = compute_fingerprint(
                self.context_manager,
                key=key,
                identifier=identifier,
                dataframe=dataframe,
                sample_rows=sample_rows,
                **options,
            )
        except Exception as error:
            self._note_fingerprint_gap(f"{scope} fingerprint for '{key}'", error)
            return None

        degraded = getattr(fingerprint, "degraded_reason", None)
        if degraded:
            self._note_fingerprint_gap(
                f"{scope} fingerprint for '{key}' degraded", RuntimeError(degraded)
            )

        if extra_details:
            fingerprint.details.update(extra_details)

        store = self.context_manager.get_or_create_dict(f"_{scope}_fingerprints")
        if store is not None:
            store[key] = fingerprint.to_dict()
        return fingerprint

    def _note_fingerprint_gap(self, what: str, error: Exception) -> None:
        """Record a fingerprinting failure as a gap in the run's evidence."""
        try:
            from ducta.core.ledger import ledger_for

            ledger_for(self._context)._note_failure(what, error)
        except Exception:  # noqa: BLE001 — reporting a gap must not create one
            logger.warning("Could not record {}: {}", what, error)
