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

The engine documents of a workspace's project, per environment — read-only views
compiled from the project's format-2 files, and whole-document writes translated
back to them (see ``V2ProjectStore.save_document``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ducta.api.exceptions import ConfigFileNotFoundError, ValidationError
from ducta.api.repositories.v2_store import DOC_FILES, V2ProjectStore, workspace_stores


class ConfigRepository:
    """Configuration documents of the workspace's project."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _store(self) -> V2ProjectStore:
        stores = workspace_stores(self._root)
        if not stores:
            raise ConfigFileNotFoundError(
                f"No Ducta project in {self._root}", detail={"root": str(self._root)}
            )
        if len(stores) > 1:
            raise ValidationError(
                "This workspace holds several projects; use the project endpoints "
                "(/projects/{id}/...) to address one of them",
                detail={"projects": [s.root.name for s in stores]},
            )
        return stores[0]

    def get_paths(self, env: str) -> Dict[str, Path]:
        store = self._store()
        return {name: store.file_for(name) for name in DOC_FILES}

    def get(self, name: str, env: str) -> Dict[str, Any]:
        docs = self._store().documents(env)
        if name not in docs:
            raise ConfigFileNotFoundError(
                f"Config '{name}' not found for environment '{env}'",
                detail={"name": name, "env": env},
            )
        return docs[name]

    def get_all(self, env: str) -> Dict[str, Dict[str, Any]]:
        return self._store().documents(env)

    def validate(self, env: str) -> Dict[str, Any]:
        from ducta.setting.project_loader import ProjectConfigError, validate_project

        errors: List[Dict[str, Any]] = []
        try:
            validate_project(self._store().root, None if env == "base" else env)
        except ProjectConfigError as exc:
            errors = [{"config": "project", "error": p} for p in exc.problems]
        return {"valid": not errors, "env": env, "errors": errors}

    def save(
        self,
        name: str,
        data: Dict[str, Any],
        env: str = "base",
        expected_sha: Optional[str] = None,
    ) -> str:
        return self._store().save_document(name, data, env, expected_sha)
