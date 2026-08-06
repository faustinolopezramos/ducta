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

Loading and caching node functions, behind the import whitelist.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.core.import_security import ModuleImportError, SecureModuleImporter
from ducta.core.settings import CoreSettings
from ducta.core.utils import compile_function


class FunctionLoader:
    """Loads and caches node functions with security validation."""

    def __init__(
        self,
        context: Any,
        is_ml_layer: bool = False,
        settings: Optional[CoreSettings] = None,
    ) -> None:
        self.context = context
        self.settings = settings or CoreSettings.from_context(context)
        self.is_ml_layer = is_ml_layer
        self._function_cache: Dict[tuple, Callable] = {}
        self._init_secure_importer()

    def _init_secure_importer(self) -> None:
        """Initialize secure module importer with context-specific configuration."""
        allowed_prefixes = getattr(self.context, "allowed_module_prefixes", None)
        additional_paths = self._gather_search_paths()
        # Whitelist enforcement is on by default; strict_module_import: false is
        # an explicit, logged opt-out resolved once in CoreSettings.
        strict_mode = self.settings.strict_module_import
        self.secure_importer = SecureModuleImporter(
            allowed_prefixes=allowed_prefixes,
            additional_search_paths=additional_paths,
            strict_mode=strict_mode,
        )
        logger.debug(
            "Secure module importer initialized (strict={}) with {} search paths",
            strict_mode,
            len(additional_paths),
        )

    def _gather_search_paths(self) -> List[Path]:
        """Gather additional module search paths from context and environment."""
        paths = []
        try:
            cwd = Path.cwd()
            paths.append(cwd)
            paths.append(cwd / "src")
            paths.append(cwd / "lib")
        except Exception as e:
            logger.debug("Could not access current working directory: {}", e)

        try:
            config_paths = getattr(self.context, "config_paths", None)
            if isinstance(config_paths, dict) and config_paths:
                first_path = next(iter(config_paths.values()))
                parent = Path(first_path).parent
                paths.append(parent)
                paths.append(parent / "src")
        except Exception:
            pass

        if hasattr(self.context, "_config_file_path"):
            try:
                config_file = Path(self.context._config_file_path)
                paths.append(config_file.parent)
                paths.append(config_file.parent / "src")
            except Exception:
                pass

        seen = set()
        unique_paths = []
        for path in paths:
            path_str = str(path)
            if path_str not in seen:
                seen.add(path_str)
                unique_paths.append(path)

        return unique_paths

    def load(self, node: Dict[str, Any]) -> Callable:
        """Load a node's function with comprehensive validation and security."""
        module_path = node.get("module")
        function_name = node.get("function")

        if not module_path or not function_name:
            node_name = node.get("name", "unknown")
            missing = []
            if not module_path:
                missing.append("'module'")
            if not function_name:
                missing.append("'function'")
            raise ValueError(
                f"Node configuration for '{node_name}' must include 'module' and 'function'. "
                f"Missing: {', '.join(missing)}. Configuration found: {node}"
            )

        cache_key = (module_path, function_name)
        cached = self._function_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            func = self.secure_importer.get_function_from_module(module_path, function_name)

            func = compile_function(func)

            try:
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())

                required_params = {"start_date", "end_date"}
                if not required_params.issubset(params):
                    logger.warning(
                        "Function '{}' may not accept required parameters: "
                        "start_date and end_date. Parameters found: {}",
                        function_name,
                        params,
                    )

                if self.is_ml_layer and "ml_context" not in params:
                    accepts_kwargs = any(
                        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                    )
                    if not accepts_kwargs:
                        logger.debug(
                            "Function '{}' doesn't accept 'ml_context' parameter nor **kwargs. "
                            "ML-specific features may not be available.",
                            function_name,
                        )
            except ValueError as e:
                logger.warning("Signature validation skipped for {}: {}", function_name, e)

            self._function_cache[cache_key] = func
            return func

        except ModuleImportError as e:
            logger.error("Security validation failed for module '{}': {}", module_path, e)
            raise ValueError(f"Cannot load node function: {e}") from e
        except Exception as e:
            logger.error(
                "Unexpected error loading function '{}' from '{}': {}",
                function_name,
                module_path,
                e,
            )
            raise
