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
    """Deletes old model versions based on a keep-newest-N retention policy,"""

    def __init__(
        self,
        storage_path: str,
        max_versions_per_model: int = 5,
        registry_path: str = "model_registry",
        model_retention_days: Optional[int] = None,
        certificate_dir: Optional[str] = None,
    ):
        self.storage_path = Path(storage_path)
        self.max_versions_per_model = max_versions_per_model
        self.model_retention_days = model_retention_days
        #: Where the run certificates are: a version one of them served is reported,
        #: since `certify verify --reproduce` of that run can no longer pin it.
        self.certificate_dir = certificate_dir
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

    def _served_by_runs(self) -> Dict[tuple, list]:
        """``{(model, version): [run_id, ...]}`` from the certificates' ``nodes[].ml.model``."""
        served: Dict[tuple, list] = {}
        if not self.certificate_dir:
            return served
        from ducta.core.certificate import iter_certificate_dirs, load_certificate

        for run_id, run_dir in iter_certificate_dirs(Path(self.certificate_dir)):
            try:
                cert = load_certificate(run_dir / "certificate.json")
            except Exception:  # noqa: BLE001 — an unreadable certificate pins nothing
                continue
            for node in cert.get("nodes") or []:
                model = ((node or {}).get("ml") or {}).get("model") or {}
                if model.get("source", "ducta") != "ducta" or model.get("version") is None:
                    continue
                key = (model.get("name"), int(model["version"]))
                served.setdefault(key, []).append(run_id)
        return served

    def run(self, dry_run: bool = False, user: Optional[str] = None) -> Dict[str, Any]:
        """Run garbage collection process; *user* is recorded in the registry's audit log."""
        stats: Dict[str, Any] = {
            "models_processed": 0,
            "versions_removed": 0,
            "bytes_freed": 0,
            # Which versions: a count alone could not be checked before running it.
            "versions": [],
        }

        try:
            models = self.registry.list_models()
        except Exception as e:
            logger.debug(f"No registry index to garbage-collect: {e}")
            return stats

        now = datetime.now(timezone.utc)
        served = self._served_by_runs()

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
                            self.registry.delete_model_version(
                                name, version_number, user=user, reason="gc"
                            )
                            logger.info(f"Deleted old model version {name} v{version_number}")
                        except ProtectedVersionError:
                            logger.info(
                                f"Skipped {name} v{version_number}: promoted to Production "
                                "since listing, no longer eligible for GC"
                            )
                            continue

                    stats["versions_removed"] += 1
                    entry = {
                        "name": name,
                        "version": version_number,
                        "created_at": v.get("created_at"),
                    }
                    runs = served.get((name, version_number))
                    if runs:
                        entry["served_in"] = runs
                        logger.warning(
                            f"{name} v{version_number} served run(s) "
                            f"{', '.join(r[:8] for r in runs)}; `certify verify --reproduce` "
                            "cannot pin it once it is deleted"
                        )
                    stats["versions"].append(entry)
                    stats["bytes_freed"] += size_bytes

            except Exception as e:
                logger.warning(f"Error processing GC for model {name}: {e}")

        return stats
