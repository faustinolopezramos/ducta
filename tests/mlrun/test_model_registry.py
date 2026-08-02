"""Unit tests for ducta.mlrun.model_registry — governance and locking behavior."""

from __future__ import annotations

import pytest

from ducta.mlrun.exceptions import ProtectedVersionError
from ducta.mlrun.gc import ModelGarbageCollector
from ducta.mlrun.model_registry import ModelRegistry, ModelStage
from ducta.mlrun.storage import LocalStorageBackend


@pytest.fixture
def registry(tmp_path):
    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)
    return ModelRegistry(storage=storage, registry_path="model_registry", validate_artifacts=False)


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
