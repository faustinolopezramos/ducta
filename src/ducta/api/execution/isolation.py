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

import sys
from typing import Set

from loguru import logger


class ModuleIsolationManager:
    """Snapshots/removes `sys.modules` entries added during an execution.

    This is in-process namespace hygiene only — it stops a pipeline's own
    `import` side effects (module-level caches, monkeypatches, singleton
    state) from leaking into the next execution that reuses the same
    process. It is NOT a security sandbox: node code still runs with the
    server's full privileges, in the server's own process, with access to
    every module already importable there (including this one). Real
    isolation would require running each pipeline in its own OS process (or
    container), which is a separate, larger change — see the execution
    module's docs for the accepted-risk note on this.
    """

    # Built-in/core modules that should never be removed
    PROTECTED_MODULES = frozenset(
        {
            "__builtin__",
            "__main__",
            "sys",
            "os",
            "builtins",
            "io",
            "pathlib",
            "threading",
            "asyncio",
            # Add other core packages as needed
        }
    )

    def __init__(self):
        self._original_modules: dict[str, Set[str]] = {}

    def snapshot_modules(self, execution_id: str) -> None:
        """Snapshot current module state before execution."""
        # Don't snapshot if already done (per-execution)
        if execution_id in self._original_modules:
            return

        current = set(sys.modules.keys())
        self._original_modules[execution_id] = current.copy()
        logger.debug(
            "Module isolation: snapshot {count} modules for execution {id}",
            count=len(current),
            id=execution_id,
        )

    def cleanup(self, execution_id: str) -> int:
        """
        Remove modules that were loaded during execution (not present in snapshot).
        Return the number of modules removed.
        """
        if execution_id not in self._original_modules:
            return 0

        original = self._original_modules[execution_id]
        current = set(sys.modules.keys())
        to_remove = current - original

        # Don't remove protected modules
        to_remove = {m for m in to_remove if not self._is_protected(m)}

        removed_count = 0
        for module_name in to_remove:
            try:
                del sys.modules[module_name]
                removed_count += 1
            except (KeyError, RuntimeError) as e:
                logger.debug(
                    "Module isolation: could not remove '{m}': {e}",
                    m=module_name,
                    e=e,
                )

        logger.debug(
            "Module isolation: removed {count} modules after execution {id}",
            count=removed_count,
            id=execution_id,
        )

        # Clean up our snapshots
        self._original_modules.pop(execution_id, None)

        return removed_count

    def cleanup_all(self) -> None:
        """Clear all snapshots (on shutdown)."""
        self._original_modules.clear()

    @staticmethod
    def _is_protected(module_name: str) -> bool:
        """Return True if this module should not be removed."""
        # Check protected list
        if module_name in ModuleIsolationManager.PROTECTED_MODULES:
            return True

        # Check prefixes: builtins, stdlib, site-packages
        if module_name.startswith("_"):
            return True
        if module_name.startswith("ducta."):
            # Keep ducta core packages
            return True
        if module_name in sys.builtin_module_names:
            return True

        return False


# Singleton instance
_module_isolation: ModuleIsolationManager | None = None


def get_module_isolation_manager() -> ModuleIsolationManager:
    """Get or create the singleton ModuleIsolationManager."""
    global _module_isolation
    if _module_isolation is None:
        _module_isolation = ModuleIsolationManager()
    return _module_isolation
