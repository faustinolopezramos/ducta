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

import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pandas as pd  # type: ignore
from loguru import logger

from ducta.mlrun.concurrency import file_lock
from ducta.mlrun.exceptions import (
    ArtifactNotFoundError,
    ModelNotFoundError,
    ModelRegistrationError,
    ProtectedVersionError,
)
from ducta.mlrun.resilience import with_mlops_resilience
from ducta.mlrun.storage import StorageBackend
from ducta.mlrun.validators import (
    ArtifactValidator,
    PathValidator,
    validate_artifact_type,
    validate_description,
    validate_framework,
    validate_model_name,
    validate_parameters,
    validate_tags,
)


class ModelStage(str, Enum):
    """Model lifecycle stage."""

    STAGING = "Staging"
    PRODUCTION = "Production"
    ARCHIVED = "Archived"


@dataclass
class PromotionPolicy:
    """Metric gate a model must pass to be promoted to Production.

    compare_to:
        - "current_production": candidate must beat the model currently in
          Production by min_delta on `metric` (first promotion passes if the
          metric exists).
        - "baseline": candidate must beat its own recorded `baseline_<metric>`
          (e.g. f1 vs baseline_f1) by min_delta — requires the training node to
          log baseline metrics (see ducta.mlrun.baseline).
    """

    metric: str
    min_delta: float = 0.0
    compare_to: str = "current_production"  # or "baseline"
    higher_is_better: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromotionPolicy":
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})


@dataclass
class ModelMetadata:
    """Model metadata."""

    name: str
    framework: str
    version: int
    created_at: str
    description: str = ""
    hyperparameters: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    tags: Dict[str, str] = field(default_factory=dict)
    stage: ModelStage = ModelStage.STAGING
    input_schema: Optional[Dict[str, str]] = None
    output_schema: Optional[Dict[str, str]] = None
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        d = asdict(self)
        d["stage"] = self.stage.value
        return d

    def validate_consistency(self, other: "ModelMetadata") -> List[str]:
        """
        Validate consistency against another metadata version.
        Useful for checking schema Drift or incompatible metrics.
        """
        warnings = []

        # Check framework consistency
        if self.framework != other.framework:
            warnings.append(f"Framework mismatch: {self.framework} vs {other.framework}")

        # Check input schema changes
        if self.input_schema != other.input_schema:
            warnings.append("Input schema has changed between versions")

        # Check for missing metrics that were previously present
        missing_metrics = set(other.metrics.keys()) - set(self.metrics.keys())
        if missing_metrics:
            warnings.append(f"Missing previously tracked metrics: {missing_metrics}")

        return warnings

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelMetadata":
        """Create from dictionary with safe field filtering."""
        # Get valid field names for this dataclass
        valid_fields = {f.name for f in fields(cls)}

        # Filter only valid fields to avoid TypeError on unknown keys
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        # Handle stage enum conversion
        filtered_data["stage"] = ModelStage(filtered_data.get("stage", "Staging"))

        return cls(**filtered_data)


@dataclass
class ModelVersion:
    """Model version information."""

    model_id: str
    version: int
    metadata: ModelMetadata
    artifact_uri: str
    artifact_type: str  # "sklearn", "xgboost", "pytorch", "onnx", etc.
    created_at: str
    updated_at: str
    experiment_run_id: Optional[str] = None
    size_bytes: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "model_id": self.model_id,
            "version": self.version,
            "metadata": self.metadata.to_dict(),
            "artifact_uri": self.artifact_uri,
            "artifact_type": self.artifact_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "experiment_run_id": self.experiment_run_id,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelVersion":
        """Create from dictionary."""
        data["metadata"] = ModelMetadata.from_dict(data["metadata"])
        return cls(**data)


class ModelRegistry:
    """
    Model Registry for versionado y gestión de modelos.
    """

    _INDEX_FILENAME = "index.parquet"

    def __init__(
        self,
        storage: StorageBackend,
        registry_path: str = "model_registry",
        validate_artifacts: bool = True,
    ):
        """
        Initialize Model Registry.

        Args:
            storage: Storage backend for artifacts
            registry_path: Base path for registry data
            validate_artifacts: When False, skip the artifact-load check in
                ``register_model`` (useful for large models to avoid doubling
                memory usage during registration).
        """
        self.storage = storage
        self.registry_path = registry_path
        self.validate_artifacts = validate_artifacts
        # Flag to track if structure has been ensured (lazy initialization)
        self._structure_ensured = False
        logger.info(f"ModelRegistry initialized at {registry_path}")

    @contextmanager
    def _registry_lock(self, timeout: float = 30.0):
        """Context manager for registry write operations"""
        lock_path = str(Path(self.registry_path) / "models.lock")
        base_path = getattr(self.storage, "base_path", None)
        with file_lock(lock_path, timeout=timeout, base_path=base_path):
            yield

    def _ensure_registry_structure(self) -> None:
        """
        Ensure registry directory structure exists (lazy initialization).
        This is only called when actually registering a model.
        """
        if self._structure_ensured:
            return

        base_path = Path(self.registry_path)
        paths = [
            str(base_path / "models"),
            str(base_path / "versions"),
            str(base_path / "artifacts"),
            str(base_path / "metadata"),
        ]
        for path in paths:
            if not self.storage.exists(path):
                # Create empty marker file
                try:
                    self.storage.write_json(
                        {"created": datetime.now(tz=timezone.utc).isoformat()},
                        str(Path(path) / ".registry_marker.json"),
                        mode="overwrite",
                    )
                except Exception:
                    pass

        self._structure_ensured = True
        logger.debug(f"Registry structure ensured at {self.registry_path}")

    def _audit_log(
        self,
        event_type: str,
        model_name: str,
        version: int,
        user: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record an event in the model audit log.
        v2.1+: Provides traceability for regulatory and compliance requirements.
        """
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "model": model_name,
            "version": version,
            "user": user or os.getenv("USER") or os.getenv("USERNAME") or "unknown",
            "reason": reason or "No reason provided",
            "details": details or {},
        }

        try:
            entry_id = str(uuid4())  # Full 128-bit UUID for collision safety
            self.storage.write_json(
                log_entry,
                str(
                    Path(self.registry_path)
                    / "metadata"
                    / f"audit_{model_name}_{version}_{entry_id}.json"
                ),
            )
        except Exception as e:
            logger.warning(f"Could not write audit log: {e}")

    @with_mlops_resilience(operation_name="register_model")
    def register_model(
        self,
        name: str,
        artifact_path: str,
        artifact_type: str,
        framework: str,
        description: str = "",
        hyperparameters: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, float]] = None,
        tags: Optional[Dict[str, str]] = None,
        input_schema: Optional[Dict[str, str]] = None,
        output_schema: Optional[Dict[str, str]] = None,
        dependencies: Optional[List[str]] = None,
        experiment_run_id: Optional[str] = None,
        audit_info: Optional[Dict[str, Optional[str]]] = None,
        trust_artifact_source: bool = False,
    ) -> ModelVersion:
        """
        Register a new model or version with validation and locking.

        `trust_artifact_source` gates whether pickle/joblib-based frameworks
        (sklearn, pickle, joblib, custom, and the pickle fallback path of
        xgboost/lightgbm) are actually deserialized during validation.
        Loading a pickle means executing it, so this defaults to False —
        artifacts from a source you haven't vetted only get a lightweight
        existence/size/extension check. Set it to True only when
        `artifact_path` is known to come from a trusted origin (the same
        trust boundary `PickleReader.allow_untrusted_pickle` enforces in
        `ducta.gate.readers`).
        """
        # Ensure registry structure exists before registering model
        self._ensure_registry_structure()

        # VALIDATION: Perform all validations before acquiring lock
        try:
            # Validate inputs
            name = validate_model_name(name)
            framework = validate_framework(framework)
            artifact_type = validate_artifact_type(artifact_type)
            description = validate_description(description)
            hyperparameters = validate_parameters(hyperparameters)
            tags = validate_tags(tags)

            logger.debug(f"Input validation passed for model '{name}'")

        except Exception as e:
            logger.error(f"Validation failed for model registration: {e}")
            raise ModelRegistrationError(name, str(e)) from e

        # ARTIFACT VALIDATION: Check artifact exists and is valid
        try:
            artifact_file = Path(artifact_path)
            PathValidator.validate_file_exists(artifact_file)
            PathValidator.validate_is_file_or_dir(artifact_file)

            # NEW: Validate that artifact can be loaded (v2.1+)
            # Set validate_artifacts=False on the ModelRegistry instance to skip
            # the expensive model-load check (e.g. for large PyTorch models).
            if self.validate_artifacts:
                ArtifactValidator.validate_artifact(
                    artifact_path=str(artifact_file),
                    framework=framework,
                    trust_artifact_source=trust_artifact_source,
                )
            logger.debug(f"Artifact validation passed: {artifact_file}")

        except Exception as e:
            logger.error(f"Artifact validation failed: {e}")
            raise ArtifactNotFoundError(artifact_path) from e

        # ATOMIC OPERATION: Register under lock
        try:
            with self._registry_lock():
                model_id = str(uuid4())
                version = 1

                # Load current index
                try:
                    models_df = self._load_models_index()
                except Exception:
                    models_df = pd.DataFrame(columns=["model_id", "name", "version", "created_at"])

                # Check if model exists (increment version)
                if "name" in models_df.columns and name in models_df["name"].values:
                    model_rows = models_df[models_df["name"] == name]
                    version = int(model_rows["version"].max()) + 1
                    model_id = model_rows["model_id"].iloc[-1]
                    logger.debug(f"Model '{name}' exists, registering version {version}")
                else:
                    logger.debug(f"Registering new model '{name}' as version 1")

                now = datetime.now(tz=timezone.utc).isoformat()

                # Create metadata
                metadata = ModelMetadata(
                    name=name,
                    framework=framework,
                    version=version,
                    created_at=now,
                    description=description,
                    hyperparameters=hyperparameters or {},
                    metrics=metrics or {},
                    tags=tags or {},
                    input_schema=input_schema,
                    output_schema=output_schema,
                    dependencies=dependencies or [],
                )

                # Copy artifact to storage
                artifact_destination = str(
                    Path(self.registry_path) / "artifacts" / model_id / f"v{version}"
                )
                artifact_metadata = self.storage.write_artifact(
                    str(artifact_file), artifact_destination, mode="overwrite"
                )

                # Create version record
                model_version = ModelVersion(
                    model_id=model_id,
                    version=version,
                    metadata=metadata,
                    artifact_uri=artifact_destination,
                    artifact_type=artifact_type,
                    created_at=now,
                    updated_at=now,
                    experiment_run_id=experiment_run_id,
                    size_bytes=artifact_metadata.size_bytes,
                )

                # Persist metadata
                metadata_path = str(
                    Path(self.registry_path) / "metadata" / model_id / f"v{version}.json"
                )
                self.storage.write_json(model_version.to_dict(), metadata_path, mode="overwrite")

                # Update index (skip_lock=True since we're already under _registry_lock)
                self._update_models_index(model_version, skip_lock=True)

                logger.info(
                    f"Registered model '{name}' version {version} "
                    f"(ID: {model_id}, size: {artifact_metadata.size_bytes} bytes)"
                )

                # NEW: record audit log (v2.1+)
                audit_user: Optional[str] = None
                audit_reason: Optional[str] = None
                if audit_info:
                    audit_user = audit_info.get("user")
                    audit_reason = audit_info.get("reason")

                self._audit_log(
                    "REGISTER",
                    name,
                    version,
                    audit_user,
                    audit_reason,
                    {
                        "framework": framework,
                        "artifact_type": artifact_type,
                        "run_id": experiment_run_id,
                    },
                )

                return model_version

        except ArtifactNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Model registration failed: {e}")
            raise ModelRegistrationError(name, str(e)) from e

    def get_model_version(
        self,
        name: str,
        version: Optional[int] = None,
    ) -> ModelVersion:
        """
        Get specific model version.
        """
        models_df = self._load_models_index()
        model_rows = models_df[models_df["name"] == name]

        if model_rows.empty:
            raise ModelNotFoundError(name)

        if version is None:
            model_rows = model_rows.sort_values("version", ascending=False)
            row = model_rows.iloc[0]
        else:
            row = model_rows[model_rows["version"] == version]
            if row.empty:
                raise ModelNotFoundError(name, version)
            row = row.iloc[0]

        metadata_path = str(
            Path(self.registry_path) / "metadata" / row["model_id"] / f"v{row['version']}.json"
        )
        data = self.storage.read_json(metadata_path)
        return ModelVersion.from_dict(data)

    def get_model_by_stage(self, name: str, stage: ModelStage) -> ModelVersion:
        """Get latest model version for a given stage."""
        models_df = self._load_models_index()
        model_rows = models_df[models_df["name"] == name]

        if model_rows.empty:
            raise ModelNotFoundError(name)

        # Fast path: filter by stage column when available in the index (N-01 optimisation)
        if "stage" in model_rows.columns:
            stage_rows = model_rows[model_rows["stage"] == stage.value]
            if not stage_rows.empty:
                # Pick highest version from index — load only that single JSON
                best_row = stage_rows.sort_values("version", ascending=False).iloc[0]
                metadata_path = str(
                    Path(self.registry_path)
                    / "metadata"
                    / best_row["model_id"]
                    / f"v{best_row['version']}.json"
                )
                data = self.storage.read_json(metadata_path)
                return ModelVersion.from_dict(data)
            raise ModelNotFoundError(f"{name} in stage {stage.value}")

        # Slow path (legacy index without stage column): iterate all version JSONs
        candidates: List[ModelVersion] = []
        for _, row in model_rows.iterrows():
            metadata_path = str(
                Path(self.registry_path) / "metadata" / row["model_id"] / f"v{row['version']}.json"
            )
            data = self.storage.read_json(metadata_path)
            mv = ModelVersion.from_dict(data)
            if mv.metadata.stage == stage:
                candidates.append(mv)

        if not candidates:
            raise ModelNotFoundError(f"{name} in stage {stage.value}")

        # Return highest version in the requested stage
        return sorted(candidates, key=lambda mv: mv.version, reverse=True)[0]

    def list_models(self) -> List[Dict[str, Any]]:
        """List all registered models with latest version."""
        models_df = self._load_models_index()
        if models_df.empty:
            return []

        latest = models_df.sort_values("version", ascending=False).drop_duplicates(
            "name", keep="first"
        )

        result = []
        for _, row in latest.iterrows():
            model_version = self.get_model_version(row["name"], int(row["version"]))
            result.append(
                {
                    "name": row["name"],
                    "model_id": row["model_id"],
                    "latest_version": int(row["version"]),
                    "stage": model_version.metadata.stage.value,
                    "created_at": model_version.created_at,
                    "framework": model_version.metadata.framework,
                }
            )

        return result

    def list_model_versions(self, name: str) -> List[Dict[str, Any]]:
        """List all versions of a model."""
        models_df = self._load_models_index()
        model_rows = models_df[models_df["name"] == name].sort_values("version", ascending=False)

        if model_rows.empty:
            raise ModelNotFoundError(name)

        result = []
        for _, row in model_rows.iterrows():
            model_version = self.get_model_version(name, int(row["version"]))
            result.append(
                {
                    "version": int(row["version"]),
                    "stage": model_version.metadata.stage.value,
                    "created_at": model_version.created_at,
                    "artifact_type": model_version.artifact_type,
                    "metrics": model_version.metadata.metrics,
                }
            )

        return result

    @with_mlops_resilience(operation_name="promote_model")
    def promote_model(
        self,
        name: str,
        version: int,
        stage: ModelStage,
        user: Optional[str] = None,
        reason: Optional[str] = None,
        policy: Optional[PromotionPolicy] = None,
        force: bool = False,
    ) -> ModelVersion:
        """
        Promote model to new stage.

        When promoting to Production with a ``policy``, the candidate must pass
        the metric gate or ``PromotionGateError`` is raised. ``force=True``
        bypasses the gate; the bypass is recorded in the audit log.

        Promoting a version to Production demotes any other version of the same
        model currently in Production to Archived, in the same locked operation —
        otherwise multiple versions could be "Production" simultaneously, and
        garbage collection (which treats every Production-staged version as
        permanently protected) would never reclaim the superseded ones.
        """
        with self._registry_lock():
            model_version = self.get_model_version(name, version)

            gate_bypassed = False
            if policy is not None and stage == ModelStage.PRODUCTION:
                if force:
                    gate_bypassed = True
                    logger.warning(
                        f"Promotion gate BYPASSED (force=True) for {name} v{version}; "
                        f"recording bypass in audit log"
                    )
                else:
                    self._check_promotion_gate(name, model_version, policy)

            old_stage = model_version.metadata.stage
            model_version.metadata.stage = stage
            model_version.updated_at = datetime.now(tz=timezone.utc).isoformat()

            metadata_path = str(
                Path(self.registry_path) / "metadata" / model_version.model_id / f"v{version}.json"
            )
            self.storage.write_json(model_version.to_dict(), metadata_path, mode="overwrite")

            demoted_versions: List[int] = []
            if stage == ModelStage.PRODUCTION:
                demoted_versions = self._demote_other_production_versions(name, version, user=user)

            # N-01: Keep stage column in index up-to-date so get_model_by_stage
            # can filter without reading all JSON files.
            self._update_models_index(model_version, skip_lock=True)

            logger.info(f"Model {name} v{version} promoted to {stage.value}")

            # NEW: record audit log (v2.1+)
            audit_details: Dict[str, Any] = {
                "old_stage": old_stage.value,
                "new_stage": stage.value,
            }
            if gate_bypassed:
                audit_details["gate_bypassed"] = True
                audit_details["policy_metric"] = policy.metric
            if demoted_versions:
                audit_details["demoted_versions"] = demoted_versions
            self._audit_log(
                "PROMOTE",
                name,
                version,
                user,
                reason,
                audit_details,
            )

            return model_version

    def _demote_other_production_versions(
        self, name: str, keep_version: int, user: Optional[str] = None
    ) -> List[int]:
        """Archive every other Production-staged version of ``name``.

        Must be called while already holding ``_registry_lock()``. Returns the
        list of version numbers that were demoted, for the caller's audit entry.
        """
        models_df = self._load_models_index()
        if models_df.empty or "stage" not in models_df.columns:
            return []

        rows = models_df[
            (models_df["name"] == name)
            & (models_df["stage"] == ModelStage.PRODUCTION.value)
            & (models_df["version"] != keep_version)
        ]

        demoted: List[int] = []
        for _, row in rows.iterrows():
            other_version = int(row["version"])
            try:
                other = self.get_model_version(name, other_version)
            except ModelNotFoundError:
                continue
            if other.metadata.stage != ModelStage.PRODUCTION:
                # Index was stale relative to the metadata file; nothing to do.
                continue

            other.metadata.stage = ModelStage.ARCHIVED
            other.updated_at = datetime.now(tz=timezone.utc).isoformat()
            other_metadata_path = str(
                Path(self.registry_path) / "metadata" / other.model_id / f"v{other_version}.json"
            )
            self.storage.write_json(other.to_dict(), other_metadata_path, mode="overwrite")
            self._update_models_index(other, skip_lock=True)
            self._audit_log(
                "DEMOTE",
                name,
                other_version,
                user,
                f"superseded by v{keep_version} promotion to Production",
                {"old_stage": ModelStage.PRODUCTION.value, "new_stage": ModelStage.ARCHIVED.value},
            )
            logger.info(
                f"Model {name} v{other_version} demoted to Archived (superseded by v{keep_version})"
            )
            demoted.append(other_version)

        return demoted

    def _check_promotion_gate(
        self, name: str, candidate: "ModelVersion", policy: PromotionPolicy
    ) -> None:
        """Validate the candidate against the promotion policy; raise on failure."""
        from ducta.mlrun.baseline import compare_to_baseline
        from ducta.mlrun.exceptions import PromotionGateError

        candidate_metrics = candidate.metadata.metrics or {}
        if policy.metric not in candidate_metrics:
            raise PromotionGateError(
                name,
                candidate.version,
                f"candidate has no '{policy.metric}' metric recorded; "
                "register models with metrics to enable gated promotion",
            )

        if policy.compare_to == "baseline":
            # Without this check compare_to_baseline falls back to comparing the
            # metric against itself (delta 0), which passes any min_delta <= 0.
            baseline_key = f"baseline_{policy.metric}"
            if baseline_key not in candidate_metrics:
                raise PromotionGateError(
                    name,
                    candidate.version,
                    f"candidate has no '{baseline_key}' metric recorded; "
                    "compare_to='baseline' requires the training node to log baseline "
                    "metrics alongside model metrics (see ducta.mlrun.baseline."
                    "trivial_baseline_metrics)",
                )
            passes, message = compare_to_baseline(
                candidate_metrics,
                candidate_metrics,
                policy.metric,
                min_delta=policy.min_delta,
                higher_is_better=policy.higher_is_better,
            )
            if not passes:
                raise PromotionGateError(name, candidate.version, message)
            logger.info(f"Promotion gate (vs baseline) passed for {name}: {message}")
            return

        if policy.compare_to != "current_production":
            raise PromotionGateError(
                name,
                candidate.version,
                f"unknown compare_to '{policy.compare_to}' (valid: current_production, baseline)",
            )

        try:
            current = self.get_model_by_stage(name, ModelStage.PRODUCTION)
        except ModelNotFoundError:
            logger.info(
                f"Promotion gate: no model in Production for '{name}' yet; "
                f"first promotion allowed with '{policy.metric}' present"
            )
            return

        current_metrics = current.metadata.metrics or {}
        if policy.metric not in current_metrics:
            logger.warning(
                f"Promotion gate: current Production model {name} v{current.version} has no "
                f"'{policy.metric}' metric; allowing promotion (cannot compare)"
            )
            return

        candidate_value = float(candidate_metrics[policy.metric])
        current_value = float(current_metrics[policy.metric])
        delta = (
            candidate_value - current_value
            if policy.higher_is_better
            else current_value - candidate_value
        )
        if delta < policy.min_delta:
            raise PromotionGateError(
                name,
                candidate.version,
                f"{policy.metric}={candidate_value:.4f} does not beat current Production "
                f"v{current.version} ({policy.metric}={current_value:.4f}) by min_delta="
                f"{policy.min_delta:+.4f} (delta={delta:+.4f})",
            )
        logger.info(
            f"Promotion gate passed for {name} v{candidate.version}: "
            f"{policy.metric} {candidate_value:.4f} vs Production {current_value:.4f} "
            f"(delta={delta:+.4f}, min={policy.min_delta:+.4f})"
        )

    def download_artifact(self, name: str, version: Optional[int], local_destination: str) -> None:
        """
        Download model artifact to local path.
        """
        model_version = self.get_model_version(name, version)
        self.storage.read_artifact(model_version.artifact_uri, local_destination)
        logger.info(f"Downloaded {name} v{model_version.version} to {local_destination}")

    def delete_model_version(self, name: str, version: int, force: bool = False) -> None:
        """Delete specific model version and remove it from the index.

        Re-reads the version's live stage under the registry lock immediately
        before deleting: if it is currently in Production, deletion is refused
        with ``ProtectedVersionError`` unless ``force=True``. This closes the
        race with garbage collection, which decides what to delete from a
        snapshot taken before this lock is acquired — if the version was
        promoted to Production in the meantime, this check catches it.
        """
        with self._registry_lock():
            model_version = self.get_model_version(name, version)

            if model_version.metadata.stage == ModelStage.PRODUCTION and not force:
                raise ProtectedVersionError(name, version, stage=ModelStage.PRODUCTION.value)

            # Delete artifact
            try:
                self.storage.delete(model_version.artifact_uri)
            except Exception as e:
                logger.warning(f"Could not delete artifact: {e}")

            # Delete metadata
            metadata_path = str(
                Path(self.registry_path) / "metadata" / model_version.model_id / f"v{version}.json"
            )
            try:
                self.storage.delete(metadata_path)
            except Exception as e:
                logger.warning(f"Could not delete metadata: {e}")

            # Remove from index (prevents corrupted index with dangling references)
            df = self._load_models_index()
            if not df.empty:
                df = df[~((df["name"] == name) & (df["version"] == version))]
                index_path = str(Path(self.registry_path) / "models" / self._INDEX_FILENAME)
                self.storage.write_dataframe(df, index_path, mode="overwrite")

        logger.info(f"Deleted {name} v{version}")

    def _load_models_index(self) -> pd.DataFrame:
        """Load models index."""
        try:
            index_path = str(Path(self.registry_path) / "models" / self._INDEX_FILENAME)
            return self.storage.read_dataframe(index_path)
        except FileNotFoundError:
            return pd.DataFrame(columns=["model_id", "name", "version", "created_at"])

    def _update_models_index(self, model_version: ModelVersion, skip_lock: bool = False) -> None:
        """
        Update models index.
        Includes the current stage so that get_model_by_stage can filter
        without reading every JSON metadata file (N-01 optimisation).
        """
        lock_path = str(Path(self.registry_path) / "models" / ".index.lock")

        def _do_update():
            df = self._load_models_index()

            new_row = pd.DataFrame(
                [
                    {
                        "model_id": model_version.model_id,
                        "name": model_version.metadata.name,
                        "version": model_version.version,
                        "created_at": model_version.created_at,
                        "stage": model_version.metadata.stage.value,
                    }
                ]
            )

            df = pd.concat([df, new_row], ignore_index=True)
            df = df.drop_duplicates(subset=["model_id", "version"], keep="last")

            index_path = str(Path(self.registry_path) / "models" / self._INDEX_FILENAME)
            self.storage.write_dataframe(df, index_path, mode="overwrite")

        if skip_lock:
            _do_update()
        else:
            with file_lock(
                lock_path, timeout=30.0, base_path=getattr(self.storage, "base_path", None)
            ):
                _do_update()
