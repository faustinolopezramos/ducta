"""The model GC says which certified runs it makes unreproducible (review 2026-11-11).

It deleted the version a certificate served without a word, and
``certify verify --reproduce`` of that run could no longer pin it. Decision: warn,
do not protect — what is deleted does not change.
"""

from __future__ import annotations

import json

import pytest

from ducta.mlrun.gc import ModelGarbageCollector
from ducta.mlrun.model_registry import ModelRegistry
from ducta.mlrun.storage import LocalStorageBackend


@pytest.fixture
def registry(tmp_path):
    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)
    return ModelRegistry(storage=storage, registry_path="model_registry", validate_artifacts=False)


def _register(registry, tmp_path, content: bytes):
    artifact = tmp_path / f"artifact_{content.decode()}.bin"
    artifact.write_bytes(content)
    return registry.register_model(
        name="churn",
        artifact_path=str(artifact),
        artifact_type="model",
        framework="sklearn",
        metrics={"f1": 0.9},
    )


def _certificate(runs_dir, run_id: str, version: int, source: str = "ducta") -> None:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    cert = {
        "run_id": run_id,
        "nodes": [
            {
                "name": "score",
                "ml": {"model": {"name": "churn", "version": version, "source": source}},
            }
        ],
    }
    (run_dir / "certificate.json").write_text(json.dumps(cert))


def _gc(tmp_path, runs_dir=None) -> ModelGarbageCollector:
    return ModelGarbageCollector(
        storage_path=str(tmp_path / "mlops"),
        max_versions_per_model=1,
        registry_path="model_registry",
        certificate_dir=str(runs_dir) if runs_dir else None,
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_deleted_version_lists_the_runs_it_served(registry, tmp_path, dry_run):
    for content in (b"v1", b"v2", b"v3"):
        _register(registry, tmp_path, content)
    runs = tmp_path / "runs"
    _certificate(runs, "run-aaaa1111", version=1)
    _certificate(runs, "run-bbbb2222", version=1)
    _certificate(runs, "run-mlflow", version=2, source="mlflow")  # not Ducta's registry

    stats = _gc(tmp_path, runs).run(dry_run=dry_run)

    assert stats["versions_removed"] == 2  # unchanged: warn, do not protect
    by_version = {v["version"]: v for v in stats["versions"]}
    assert sorted(by_version[1]["served_in"]) == ["run-aaaa1111", "run-bbbb2222"]
    assert "served_in" not in by_version[2]


def test_without_certificate_dir_nothing_changes(registry, tmp_path):
    for content in (b"v1", b"v2"):
        _register(registry, tmp_path, content)
    stats = _gc(tmp_path).run(dry_run=True)
    assert stats["versions_removed"] == 1
    assert all("served_in" not in v for v in stats["versions"])


def test_unreadable_certificate_is_skipped(registry, tmp_path):
    for content in (b"v1", b"v2"):
        _register(registry, tmp_path, content)
    runs = tmp_path / "runs"
    (runs / "broken").mkdir(parents=True)
    (runs / "broken" / "certificate.json").write_text("{not json")
    assert _gc(tmp_path, runs).run(dry_run=True)["versions_removed"] == 1
