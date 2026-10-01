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

from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

#: The two views of the catalog.
_INPUT_KEY = "input"
_OUTPUT_KEY = "output"


class DatasetRepository:
    """Reads the ``input_config`` / ``output_config`` dataset registries."""

    def __init__(self, root: Path) -> None:
        self._root = root

    # ── Queries ───────────────────────────────────────────────────────────────

    def list_inputs(self) -> Dict[str, Any]:
        """Return every declared input dataset keyed by reference name."""
        return self._list_side(_INPUT_KEY)

    def list_outputs(self) -> Dict[str, Any]:
        """Return every declared output dataset keyed by reference name."""
        return self._list_side(_OUTPUT_KEY)

    def resolve(self, name: str, side: str) -> Optional[Dict[str, Any]]:
        """Return the registry entry for *name*, or ``None`` when undeclared."""
        return self.resolve_from(name, side, self.list_inputs(), self.list_outputs())

    @staticmethod
    def resolve_from(
        name: str, side: str, inputs: Dict[str, Any], outputs: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Same lookup as :meth:`resolve`, against registries the caller already loaded —
        lets a batch caller load ``inputs``/``outputs`` once and resolve many names."""
        primary = inputs if side == _INPUT_KEY else outputs
        entry = primary.get(name)
        if entry is not None:
            return entry if isinstance(entry, dict) else {"format": str(entry)}

        secondary = outputs if side == _INPUT_KEY else inputs
        entry = secondary.get(name)
        if entry is None:
            return None
        return entry if isinstance(entry, dict) else {"format": str(entry)}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _list_side(self, key: str) -> Dict[str, Any]:
        """The ``input``/``output`` view of every project's catalog in the workspace."""
        from ducta.api.repositories.v2_store import workspace_stores

        registry: Dict[str, Any] = {}
        for store in workspace_stores(self._root):
            try:
                registry.update(store.documents().get(key, {}) or {})
            except Exception as exc:  # noqa: BLE001 - an invalid project must not 500 the route
                logger.warning(
                    "Failed to compile the catalog of {proj}: {exc}", proj=store.root.name, exc=exc
                )
        return registry
