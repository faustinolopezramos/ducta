"""Unit tests for ducta.mlrun.model_registry — governance and locking behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ducta.mlrun.exceptions import ArtifactNotFoundError, ArtifactValidationError, ProtectedVersionError
from ducta.mlrun.gc import ModelGarbageCollector
from ducta.mlrun.model_registry import ModelRegistry, ModelStage
from ducta.mlrun.storage import LocalStorageBackend


@pytest.fixture
def registry(tmp_path):
    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)
    return ModelRegistry(storage=storage, registry_path="model_registry", validate_artifacts=False)


@pytest.fixture
def validating_registry(tmp_path):
    """A registry with validate_artifacts=True (the default) — needed to
    exercise ArtifactValidator, which the `registry` fixture above bypasses."""
    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)
    return ModelRegistry(storage=storage, registry_path="model_registry")


def _register(registry, tmp_path, name="my-model", content=b"weights"):
    artifact = tmp_path / f"artifact_{content!r}.bin"
    artifact.write_bytes(content)
    return registry.register_model(
        name=name,
        artifact_path=str(artifact),
        artifact_type="model",
        framework="sklearn",
        metrics={"f1": 0.9},
    )


class TestPromoteDemotesPrevious:
    def test_promoting_new_version_demotes_previous_production(self, registry, tmp_path):
        v1 = _register(registry, tmp_path, content=b"v1")
        v2 = _register(registry, tmp_path, content=b"v2")

        registry.promote_model("my-model", v1.version, ModelStage.PRODUCTION)
        registry.promote_model("my-model", v2.version, ModelStage.PRODUCTION)

        reloaded_v1 = registry.get_model_version("my-model", v1.version)
        reloaded_v2 = registry.get_model_version("my-model", v2.version)
        assert reloaded_v1.metadata.stage == ModelStage.ARCHIVED
        assert reloaded_v2.metadata.stage == ModelStage.PRODUCTION

    def test_only_one_production_version_at_a_time(self, registry, tmp_path):
        v1 = _register(registry, tmp_path, content=b"v1")
        v2 = _register(registry, tmp_path, content=b"v2")
        v3 = _register(registry, tmp_path, content=b"v3")

        registry.promote_model("my-model", v1.version, ModelStage.PRODUCTION)
        registry.promote_model("my-model", v2.version, ModelStage.PRODUCTION)
        registry.promote_model("my-model", v3.version, ModelStage.PRODUCTION)

        versions = registry.list_model_versions("my-model")
        production = [v for v in versions if v["stage"] == ModelStage.PRODUCTION.value]
        assert len(production) == 1
        assert production[0]["version"] == v3.version

    def test_promoting_to_staging_does_not_demote_production(self, registry, tmp_path):
        v1 = _register(registry, tmp_path, content=b"v1")
        v2 = _register(registry, tmp_path, content=b"v2")

        registry.promote_model("my-model", v1.version, ModelStage.PRODUCTION)
        registry.promote_model("my-model", v2.version, ModelStage.STAGING)

        reloaded_v1 = registry.get_model_version("my-model", v1.version)
        assert reloaded_v1.metadata.stage == ModelStage.PRODUCTION


class TestDeleteProtectsProduction:
    def test_delete_production_version_is_refused(self, registry, tmp_path):
        v1 = _register(registry, tmp_path, content=b"v1")
        registry.promote_model("my-model", v1.version, ModelStage.PRODUCTION)

        with pytest.raises(ProtectedVersionError):
            registry.delete_model_version("my-model", v1.version)

        # Still present after the refused delete.
        assert registry.get_model_version("my-model", v1.version) is not None

    def test_delete_production_version_with_force_succeeds(self, registry, tmp_path):
        v1 = _register(registry, tmp_path, content=b"v1")
        registry.promote_model("my-model", v1.version, ModelStage.PRODUCTION)

        registry.delete_model_version("my-model", v1.version, force=True)

        with pytest.raises(Exception):
            registry.get_model_version("my-model", v1.version)

    def test_delete_non_production_version_succeeds(self, registry, tmp_path):
        v1 = _register(registry, tmp_path, content=b"v1")
        registry.delete_model_version("my-model", v1.version)
        with pytest.raises(Exception):
            registry.get_model_version("my-model", v1.version)


class TestGarbageCollectionRespectsLiveState:
    def test_gc_skips_version_promoted_after_listing(self, registry, tmp_path):
        # 6 old versions beyond max_versions_per_model=1, plus one that gets
        # promoted to Production between GC's listing and its delete call —
        # simulated here by promoting it before run() reads the live registry
        # (run() re-checks live state at delete time via delete_model_version).
        versions = [_register(registry, tmp_path, content=f"v{i}".encode()) for i in range(4)]
        registry.promote_model("my-model", versions[1].version, ModelStage.PRODUCTION)

        gc = ModelGarbageCollector(
            storage_path=str(tmp_path / "mlops"),
            max_versions_per_model=1,
            registry_path="model_registry",
        )
        stats = gc.run(dry_run=False)

        assert stats["models_processed"] == 1
        # The Production version must survive regardless of retention count.
        surviving = registry.get_model_version("my-model", versions[1].version)
        assert surviving.metadata.stage == ModelStage.PRODUCTION


class TestArtifactErrorTyping:
    """register_model used to wrap every artifact-validation failure —
    corrupt pickle, wrong framework, directory rejected outright — in
    ArtifactNotFoundError, even though the artifact exists on disk. A
    present-but-invalid artifact must raise ArtifactValidationError instead,
    which is a different, actionable signal for the caller."""

    def test_corrupt_artifact_raises_artifact_validation_error(
        self, validating_registry, tmp_path
    ):
        artifact = tmp_path / "corrupt.pkl"
        artifact.write_bytes(b"")  # empty file: exists, but not a valid pickle

        with pytest.raises(ArtifactValidationError) as excinfo:
            validating_registry.register_model(
                name="corrupt-model",
                artifact_path=str(artifact),
                artifact_type="model",
                framework="sklearn",
            )
        assert not isinstance(excinfo.value, ArtifactNotFoundError)

    def test_missing_artifact_still_raises_artifact_not_found_error(
        self, validating_registry, tmp_path
    ):
        with pytest.raises(ArtifactNotFoundError):
            validating_registry.register_model(
                name="missing-model",
                artifact_path=str(tmp_path / "does_not_exist.pkl"),
                artifact_type="model",
                framework="sklearn",
            )

    def test_directory_artifact_is_not_rejected_for_being_a_directory(self, tmp_path):
        """ArtifactValidator used to hard-reject any non-file path before
        ever reaching a framework's loader, even though PathValidator (used
        just before it in register_model) explicitly allows directories and
        StorageBackend.write_artifact copies them fine (TensorFlow
        SavedModel, checkpoint dirs, ...). Test the validator directly since
        it doesn't require tensorflow to be installed — the loader dispatch
        catches ImportError and skips, it just must never get a blanket
        "not a file" rejection first."""
        from ducta.mlrun.validators import ArtifactValidator

        model_dir = tmp_path / "saved_model"
        model_dir.mkdir()
        (model_dir / "saved_model.pb").write_bytes(b"\x00")

        # Must not raise for being a directory (may warn/skip if tensorflow
        # isn't installed in this environment — that's a different, acceptable
        # outcome from the "artifact path must be a file" rejection this test
        # guards against).
        ArtifactValidator.validate_artifact(
            artifact_path=str(model_dir), framework="tensorflow", trust_artifact_source=False
        )


class TestRegisterPromoteHaveNoAutoRetry:
    """register_model/promote_model used to carry @with_mlops_resilience
    (retry). Both mutate on-disk state across multiple non-atomic steps
    (copy artifact, write metadata, update index / demote others), so a
    transient failure partway through and a blind retry of the whole
    function can double-register or double-promote. A single failure must
    now propagate immediately — exactly once, no retry."""

    def test_register_model_does_not_retry_on_failure(self, registry, tmp_path, monkeypatch):
        artifact = tmp_path / "m.bin"
        artifact.write_bytes(b"weights")

        calls = {"n": 0}
        original_write_artifact = registry.storage.write_artifact

        def failing_write_artifact(*args, **kwargs):
            calls["n"] += 1
            raise OSError("simulated transient failure")

        monkeypatch.setattr(registry.storage, "write_artifact", failing_write_artifact)

        with pytest.raises(Exception):
            registry.register_model(
                name="flaky-model",
                artifact_path=str(artifact),
                artifact_type="model",
                framework="sklearn",
            )
        assert calls["n"] == 1

        # No half-registered version left behind in the index.
        monkeypatch.setattr(registry.storage, "write_artifact", original_write_artifact)
        with pytest.raises(Exception):
            registry.get_model_version("flaky-model")

    def test_promote_model_does_not_retry_on_failure(self, registry, tmp_path, monkeypatch):
        v1 = _register(registry, tmp_path, content=b"v1")

        calls = {"n": 0}

        def failing_write_json(*args, **kwargs):
            calls["n"] += 1
            raise OSError("simulated transient failure")

        monkeypatch.setattr(registry.storage, "write_json", failing_write_json)

        with pytest.raises(Exception):
            registry.promote_model("my-model", v1.version, ModelStage.PRODUCTION)
        assert calls["n"] == 1


class TestListModelVersionsLite:
    """list_model_versions_lite answers from the models index alone (no
    per-version JSON reads) — gc.py's whole reason for existing."""

    def test_matches_full_list_for_version_and_stage(self, registry, tmp_path):
        v1 = _register(registry, tmp_path, content=b"v1")
        v2 = _register(registry, tmp_path, content=b"v2")
        registry.promote_model("my-model", v2.version, ModelStage.PRODUCTION)

        lite = {v["version"]: v for v in registry.list_model_versions_lite("my-model")}
        full = {v["version"]: v for v in registry.list_model_versions("my-model")}

        assert set(lite) == {v1.version, v2.version}
        for version in lite:
            assert lite[version]["stage"] == full[version]["stage"]
            assert lite[version]["created_at"] == full[version]["created_at"]
            assert lite[version]["size_bytes"] == len(b"v1")  # "v1"/"v2" are both 2 bytes

    def test_falls_back_to_full_read_for_legacy_index_without_size_bytes(
        self, registry, tmp_path
    ):
        _register(registry, tmp_path, content=b"v1")

        # Simulate a legacy on-disk index predating the size_bytes column.
        index_path = "model_registry/models/index.parquet"
        df = registry.storage.read_dataframe(index_path)
        df = df.drop(columns=["size_bytes"])
        registry.storage.write_dataframe(df, index_path, mode="overwrite")

        lite = registry.list_model_versions_lite("my-model")
        assert len(lite) == 1
        assert lite[0]["size_bytes"] == len(b"v1")

    def test_unknown_model_raises(self, registry):
        from ducta.mlrun.exceptions import ModelNotFoundError

        with pytest.raises(ModelNotFoundError):
            registry.list_model_versions_lite("nonexistent")


class TestGarbageCollectionRetentionDays:
    """model_retention_days combines with max_versions_per_model via
    OR-permissive semantics: a version survives if it's within the
    newest-N budget OR younger than the retention window; it's deleted only
    if it fails both."""

    def _register_with_age(self, registry, tmp_path, content, days_old):
        version = _register(registry, tmp_path, content=content)
        mv = registry.get_model_version("my-model", version.version)
        mv.created_at = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
        import json as _json
        from pathlib import Path as _Path

        metadata_path = (
            tmp_path / "mlops" / "model_registry" / "metadata" / mv.model_id / f"v{mv.version}.json"
        )
        data = _json.loads(metadata_path.read_text())
        data["created_at"] = mv.created_at
        metadata_path.write_text(_json.dumps(data))

        # Keep the index's created_at in sync too (list_model_versions_lite
        # reads it from there).
        index_path = "model_registry/models/index.parquet"
        df = registry.storage.read_dataframe(index_path)
        df.loc[df["version"] == version.version, "created_at"] = mv.created_at
        registry.storage.write_dataframe(df, index_path, mode="overwrite")
        return version

    def test_retention_days_protects_young_versions_beyond_count_budget(self, registry, tmp_path):
        for i in range(4):
            self._register_with_age(registry, tmp_path, content=f"v{i}".encode(), days_old=1)

        gc = ModelGarbageCollector(
            storage_path=str(tmp_path / "mlops"),
            max_versions_per_model=1,
            registry_path="model_registry",
            model_retention_days=30,
        )
        stats = gc.run(dry_run=False)
        assert stats["versions_removed"] == 0

    def test_old_versions_beyond_count_budget_are_still_removed(self, registry, tmp_path):
        for i in range(4):
            self._register_with_age(registry, tmp_path, content=f"v{i}".encode(), days_old=90)

        gc = ModelGarbageCollector(
            storage_path=str(tmp_path / "mlops"),
            max_versions_per_model=1,
            registry_path="model_registry",
            model_retention_days=30,
        )
        stats = gc.run(dry_run=False)
        assert stats["versions_removed"] == 3

    def test_no_retention_days_keeps_original_count_only_behavior(self, registry, tmp_path):
        for i in range(4):
            self._register_with_age(registry, tmp_path, content=f"v{i}".encode(), days_old=1)

        gc = ModelGarbageCollector(
            storage_path=str(tmp_path / "mlops"),
            max_versions_per_model=1,
            registry_path="model_registry",
            model_retention_days=None,
        )
        stats = gc.run(dry_run=False)
        assert stats["versions_removed"] == 3
