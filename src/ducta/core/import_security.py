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

import importlib
import importlib.util
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, List, Optional

from loguru import logger  # type: ignore


class ModuleImportError(Exception):
    """Exception raised when module import fails security validation."""

    pass


class SecureModuleImporter:
    """
    Secure module importer with strict validation and cleanup.
    """

    DEFAULT_ALLOWED_PREFIXES = [
        "ducta.",
        "nodes.",
        "custom_nodes.",
        "src.",
        "lib.",
        "pipelines.",
        "transformations.",
        "data.",
    ]

    FORBIDDEN_PATTERNS = [
        r"\.\.",  # Parent directory traversal
        r"^/",  # Absolute paths
        r"^[A-Z]:",  # Windows drive letters
        r"__import__",  # Direct import manipulation
    ]

    MAX_MODULE_PATH_LENGTH = 256
    MAX_CACHE_SIZE = 128

    def __init__(
        self,
        allowed_prefixes: Optional[List[str]] = None,
        additional_search_paths: Optional[List[Path]] = None,
        strict_mode: bool = True,
    ):
        """
        Initialize secure module importer.
        """
        self.allowed_prefixes = allowed_prefixes or self.DEFAULT_ALLOWED_PREFIXES
        self.strict_mode = strict_mode
        self._module_cache: dict = {}

        self.additional_search_paths = []
        if additional_search_paths:
            for path in additional_search_paths:
                validated = self._validate_search_path(path)
                if validated:
                    self.additional_search_paths.append(validated)

    def _validate_search_path(self, path: Path) -> Optional[Path]:
        """
        Validate that a search path is safe to add to sys.path.
        """
        try:
            resolved_path = path.resolve(strict=False)

            if not resolved_path.exists() or not resolved_path.is_dir():
                logger.debug("Search path does not exist or is not a directory: {}", path)
                return None

            path_str = str(resolved_path)
            if ".." in path_str:
                logger.warning("Search path contains parent directory traversal: {}", path)
                return None

            if not os.access(resolved_path, os.R_OK):
                logger.warning("Search path is not readable: {}", path)
                return None

            return resolved_path

        except (ValueError, OSError, RuntimeError) as e:
            logger.warning("Error validating search path {}: {}", path, e)
            return None

    def validate_module_path(self, module_path: str) -> bool:
        """
        Validate that a module path is safe to import.
        """
        if len(module_path) > self.MAX_MODULE_PATH_LENGTH:
            raise ModuleImportError(
                f"Module path exceeds maximum length ({self.MAX_MODULE_PATH_LENGTH}): {module_path}"
            )

        if not module_path or not module_path.strip():
            raise ModuleImportError("Module path cannot be empty")

        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, module_path):
                raise ModuleImportError(
                    f"Module path contains forbidden pattern '{pattern}': {module_path}"
                )

        if not re.match(r"^[a-zA-Z0-9_\.]+$", module_path):
            raise ModuleImportError(
                f"Module path contains invalid characters (only [a-zA-Z0-9_.] allowed): {module_path}"
            )

        if self.strict_mode:
            if not any(module_path.startswith(prefix) for prefix in self.allowed_prefixes):
                raise ModuleImportError(
                    f"Module path '{module_path}' not in whitelist. "
                    f"Allowed prefixes: {', '.join(self.allowed_prefixes)}"
                )
        else:
            if not any(module_path.startswith(prefix) for prefix in self.allowed_prefixes):
                logger.warning(
                    f"Module '{module_path}' not in whitelist prefixes but allowed because "
                    "strict_mode is disabled (global_settings.strict_module_import: false). "
                    "This bypasses the import whitelist security boundary."
                )

        return True

    @contextmanager
    def temporary_sys_path(self, additional_paths: Optional[List[str]] = None):
        """
        Context manager to temporarily add paths to sys.path with guaranteed cleanup.
        """
        original_sys_path = sys.path.copy()
        added_paths = []

        try:
            if additional_paths:
                for path_str in additional_paths:
                    path = Path(path_str)
                    validated = self._validate_search_path(path)
                    if validated and str(validated) not in sys.path:
                        sys.path.insert(0, str(validated))
                        added_paths.append(str(validated))
                        logger.debug("Temporarily added to sys.path: {}", validated)

            for path in self.additional_search_paths:
                if str(path) not in sys.path:
                    sys.path.insert(0, str(path))
                    added_paths.append(str(path))

            yield

        finally:
            sys.path[:] = original_sys_path
            if added_paths:
                logger.debug("Cleaned up {} temporary sys.path entries", len(added_paths))

    def import_module(self, module_path: str) -> Any:
        """
        Securely import a module with validation and per-instance caching.
        """
        self.validate_module_path(module_path)

        if module_path in self._module_cache:
            logger.debug("Using cached module: {}", module_path)
            return self._module_cache[module_path]

        try:
            module = importlib.import_module(module_path)
            self._cache_module(module_path, module)
            logger.debug("Successfully imported module: {}", module_path)
            return module

        except ImportError as e:
            logger.debug("Standard import failed for '{}': {}", module_path, e)

            return self._import_with_fallback(module_path, e)

    def _cache_module(self, module_path: str, module: Any) -> None:
        """Cache imported module with bounded size eviction."""
        if len(self._module_cache) >= self.MAX_CACHE_SIZE:
            self._module_cache.pop(next(iter(self._module_cache)))
        self._module_cache[module_path] = module

    def _import_with_fallback(self, module_path: str, original_error: ImportError) -> Any:
        """
        Attempt import with additional search paths.
        """
        if not self.additional_search_paths:
            raise ModuleImportError(
                f"Cannot import module '{module_path}': {original_error}"
            ) from original_error

        with self.temporary_sys_path():
            try:
                module = importlib.import_module(module_path)
                self._cache_module(module_path, module)
                logger.info("Successfully imported '{}' using fallback paths", module_path)
                return module

            except ImportError as e:
                logger.error("Failed to import '{}' even with fallback paths: {}", module_path, e)
                raise ModuleImportError(
                    f"Cannot import module '{module_path}' after trying all search paths. "
                    f"Original error: {original_error}. Fallback error: {e}"
                ) from e

    def get_function_from_module(self, module_path: str, function_name: str) -> Any:
        """
        Securely import a module and extract a specific function.
        """
        if not re.match(r"^[a-zA-Z_]\w*$", function_name):
            raise ModuleImportError(
                f"Invalid function name format: {function_name}. "
                "Must start with letter or underscore, followed by alphanumeric/underscore."
            )

        module = self.import_module(module_path)

        if not hasattr(module, function_name):
            available_functions = [
                name
                for name in dir(module)
                if callable(getattr(module, name)) and not name.startswith("_")
            ]
            raise ModuleImportError(
                f"Function '{function_name}' not found in module '{module_path}'. "
                f"Available functions: {', '.join(available_functions[:10])}"
                + (
                    f" (and {len(available_functions) - 10} more)"
                    if len(available_functions) > 10
                    else ""
                )
            )

        func = getattr(module, function_name)

        if not callable(func):
            raise ModuleImportError(
                f"'{function_name}' in module '{module_path}' is not callable (type: {type(func).__name__})"
            )

        logger.debug("Successfully loaded function '{}' from '{}'", function_name, module_path)
        return func

    def clear_cache(self) -> None:
        """Clear the per-instance module import cache."""
        self._module_cache.clear()
        logger.debug("Module import cache cleared")

    def get_cache_info(self) -> dict:
        """
        Get information about the per-instance import cache.
        """
        return {
            "cached_modules": len(self._module_cache),
            "max_size": self.MAX_CACHE_SIZE,
        }
