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

from typing import Any, Optional

from loguru import logger  # type: ignore

from ducta.gate.exceptions import ConfigurationError


class ContextManager:
    """Centralized context manager for unified access to configuration and resources."""

    def __init__(self, context: Any):
        """Initialize context manager with either dict or object context."""
        if context is None:
            raise ConfigurationError("Context cannot be None") from None
        self._context = context
        self._is_dict_context = isinstance(context, dict)
        logger.debug(
            "ContextManager initialized with {} context",
            "dict" if self._is_dict_context else "object",
        )

    @staticmethod
    def _safe_get(obj: Any, key: str, default: Optional[Any] = None) -> Any:
        """Read ``key`` off obj whether it is a dict or an attribute-holding object."""
        try:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)
        except Exception as error:
            logger.debug("Error accessing key '{}' on {}: {}", key, type(obj).__name__, error)
            return default

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """Safe get from context for both dict and object."""
        return self._safe_get(self._context, key, default)

    def get_nested(self, path: str, default: Optional[Any] = None) -> Any:
        """Safe get by dot-separated path, resolving dict-vs-object at every level.

        Each segment of ``path`` may live on a dict or an attribute-holding object,
        independent of what the previous segment resolved to (e.g. ``global_settings``
        can be a dict even when the root context is an object, and vice versa).
        """
        node: Any = self._context
        for segment in path.split("."):
            if node is None:
                return default
            node = self._safe_get(node, segment, None)
        return default if node is None else node

    def set(self, key: str, value: Any) -> bool:
        """Set a top-level key on the context; returns False if the context rejects it."""
        try:
            if self._is_dict_context:
                self._context[key] = value
            else:
                setattr(self._context, key, value)
            return True
        except Exception as error:
            logger.debug("Could not set context key '{}': {}", key, error)
            return False

    def get_or_create_dict(self, key: str) -> Optional[dict]:
        """Return the dict stored at ``key``, creating and attaching one if absent.

        Returns None only if the context rejects the write (e.g. ``__slots__``).
        """
        current = self.get(key)
        if isinstance(current, dict):
            return current
        new_dict: dict = {}
        return new_dict if self.set(key, new_dict) else None

    def get_spark(self) -> Optional[Any]:
        """Get SparkSession if present, else None."""
        return self.get("spark")

    def get_execution_mode(self) -> Optional[str]:
        """Get normalized execution mode."""
        mode = self.get("execution_mode")
        if not mode:
            return None

        try:
            if not isinstance(mode, str) and hasattr(mode, "value"):
                mode = str(mode.value)
        except Exception as error:
            logger.debug("Could not normalize execution_mode value '{}': {}", mode, error)

        mode = str(mode).lower()
        if mode == "databricks":
            return "distributed"
        return mode

    def is_local_mode(self) -> bool:
        """Check if execution mode is local."""
        return self.get_execution_mode() == "local"

    def is_spark_available(self) -> bool:
        """Check if Spark context is available."""
        return self.get_spark() is not None
