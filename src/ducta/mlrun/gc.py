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

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from ducta.mlrun.exceptions import ProtectedVersionError
from ducta.mlrun.model_registry import ModelRegistry, ModelStage
from ducta.mlrun.storage import LocalStorageBackend


class ModelGarbageCollector:
    """Deletes old model versions based on a keep-newest-N retention policy,
    """

    def __init__(
        self,
        storage_path: str,
        max_versions_per_model: int = 5,
        registry_path: str = "model_registry",
        model_retention_days: Optional[int] = None,
    ):

        self.storage_path = Path(storage_path)
        self.max_versions_per_model = max_versions_per_model
        self.model_retention_days = model_retention_days
        storage = LocalStorageBackend(base_path=str(self.storage_path))
        self.registry = ModelRegistry(storage=storage, registry_path=registry_path)

    def _is_within_retention(self, created_at: Optional[str], now: datetime) -> bool:
        """True if ``created_at`` (ISO timestamp) is younger than
        ``model_retention_days``. Unparsable/missing timestamps are treated
        as NOT within retention (i.e. they don't get a free pass) rather than
        silently protecting a version whose age we can't determine."""
        if not created_at or self.model_retention_days is None:
            return False
        try:
            created = datetime.fromisoformat(created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return False
        return (now - created) < timedelta(days=self.model_retention_days)

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

        now = datetime.now(timezone.utc)

        for model in models:
            name = model.get("name")
            if not name:
                continue
            stats["models_processed"] += 1

            try:

                versions = self.registry.list_model_versions_lite(name)
                versions.sort(key=lambda v: v.get("version", 0), reverse=True)

                kept_count = 0
                for v in versions:
                    version_number = int(v["version"])
                    in_production = str(v.get("stage", "")) == ModelStage.PRODUCTION.value
                    within_count_budget = kept_count < self.max_versions_per_model
                    within_retention = self._is_within_retention(v.get("created_at"), now)

                    if in_production or within_count_budget or within_retention:
                        kept_count += 1
                        continue

                    size_bytes = int(v.get("size_bytes") or 0)

                    if dry_run:
                        logger.info(
                            f"[DRY-RUN] Would delete old model version {name} v{version_number}"
                        )
                    else:
                        try:
                            self.registry.delete_model_version(name, version_number)
                            logger.info(f"Deleted old model version {name} v{version_number}")
                        except ProtectedVersionError:

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
