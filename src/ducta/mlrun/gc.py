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
from typing import Any, Dict

from loguru import logger

from ducta.mlrun.exceptions import ProtectedVersionError
from ducta.mlrun.model_registry import ModelRegistry, ModelStage
from ducta.mlrun.storage import LocalStorageBackend


class ModelGarbageCollector:
    """Deletes old model versions based on a keep-newest-N retention policy.

    Versions in Production are always kept, regardless of age.
    """

    def __init__(
        self,
        storage_path: str,
        max_versions_per_model: int = 5,
        registry_path: str = "model_registry",
    ):
        self.storage_path = Path(storage_path)
        self.max_versions_per_model = max_versions_per_model
        storage = LocalStorageBackend(base_path=str(self.storage_path))
        self.registry = ModelRegistry(storage=storage, registry_path=registry_path)

    def run(self, dry_run: bool = False) -> Dict[str, Any]:
        """Run garbage collection process."""
        stats: Dict[str, Any] = {
            "models_processed": 0,
            "versions_removed": 0,
            "bytes_freed": 0,
        }

        try:
            models = self.registry.list_models()
        except Exception as e:
            logger.debug(f"No registry index to garbage-collect: {e}")
            return stats

        for model in models:
            name = model.get("name")
            if not name:
                continue
            stats["models_processed"] += 1

            try:
                versions = self.registry.list_model_versions(name)
                versions.sort(key=lambda v: v.get("version", 0), reverse=True)

                kept_count = 0
                for v in versions:
                    version_number = int(v["version"])
                    in_production = str(v.get("stage", "")) == ModelStage.PRODUCTION.value
                    if in_production or kept_count < self.max_versions_per_model:
                        kept_count += 1
                        continue

                    size_bytes = 0
                    try:
                        mv = self.registry.get_model_version(name, version_number)
                        size_bytes = mv.size_bytes or 0
                    except Exception:
                        pass

                    if dry_run:
                        logger.info(
                            f"[DRY-RUN] Would delete old model version {name} v{version_number}"
                        )
                    else:
                        try:
                            self.registry.delete_model_version(name, version_number)
                            logger.info(f"Deleted old model version {name} v{version_number}")
                        except ProtectedVersionError:
                            # Promoted to Production after this GC pass listed it —
                            # the registry's live re-check refused the delete.
                            logger.info(
                                f"Skipped {name} v{version_number}: promoted to Production "
                                "since listing, no longer eligible for GC"
                            )
                            continue

                    stats["versions_removed"] += 1
                    stats["bytes_freed"] += size_bytes

            except Exception as e:
                logger.warning(f"Error processing GC for model {name}: {e}")

        return stats
