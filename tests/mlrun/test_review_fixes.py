"""Regression tests for the ``ducta.mlrun`` review (2026-10-26)."""

from __future__ import annotations

import json
import os
import socket
import sys
import time

import numpy as np
import pandas as pd
import pytest

from ducta.mlrun.concurrency import FileLock
from ducta.mlrun.exceptions import InvalidParameterError
from ducta.mlrun.experiment_tracking import ExperimentTracker
from ducta.mlrun.hyperparams import HyperparamConfig, IntegerRange
from ducta.mlrun.model_registry import ModelRegistry
from ducta.mlrun.search import RandomSearch
from ducta.mlrun.storage import LocalStorageBackend
from ducta.mlrun.validators import validate_metrics, validate_parameters


@pytest.fixture(autouse=True)
def _no_stub_modules(monkeypatch):
    # same guard as tests/mlrun/test_training.py: sklearn trips over stub polars/pyspark
    for name in ("polars", "pyspark", "pyspark.sql"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None) is None:
            monkeypatch.delitem(sys.modules, name)


@pytest.fixture
def storage(tmp_path):
    return LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)


@pytest.fixture
def registry(storage):
    return ModelRegistry(storage=storage, registry_path="model_registry", validate_artifacts=False)


@pytest.fixture
def tracker(storage):
    return ExperimentTracker(storage=storage, tracking_path="experiment_tracking")


def _register(registry, tmp_path, content: bytes, name="m"):
    artifact = tmp_path / f"a_{content!r}.bin"
    artifact.write_bytes(content)
    return registry.register_model(
        name=name, artifact_path=str(artifact), artifact_type="model", framework="sklearn"
    )


class TestParametersAndMetricsFromRealTraining:
    def test_sequences_and_dicts_of_scalars_are_parameters(self):
        cleaned = validate_parameters(
            {"hidden_layer_sizes": (50, 20), "class_weight": {0: 1, 1: 5}, "alpha": 0.1}
        )
        assert cleaned == {
            "hidden_layer_sizes": [50, 20],
            "class_weight": {"0": 1, "1": 5},
            "alpha": 0.1,
        }
        json.dumps(cleaned)

    def test_numpy_scalars_become_plain_numbers(self):
        cleaned = validate_parameters({"n": np.int64(3), "lr": np.float32(0.5)})
        assert not isinstance(cleaned["n"], np.generic)
        assert not isinstance(cleaned["lr"], np.generic)
        metrics = validate_metrics({"f1": np.float32(0.25), "n": np.int64(4)})
        assert metrics == {"f1": 0.25, "n": 4.0}
        assert not any(isinstance(v, np.generic) for v in metrics.values())

    def test_an_arbitrary_object_is_still_rejected(self):
        with pytest.raises(InvalidParameterError):
            validate_parameters({"model": object()})
        with pytest.raises(InvalidParameterError):
            validate_parameters({"nested": [[[[[1]]]]]})

    def test_a_tracker_logs_numpy_metrics(self, tracker):
        exp = tracker.create_experiment("e")
        run = tracker.start_run(experiment_id=exp.experiment_id, name="r")
        tracker.log_metric(run.run_id, "acc", np.float32(0.5))
        tracker.log_metric(run.run_id, "n", np.int64(3))
        tracker.end_run(run.run_id)
        stored = tracker.get_run(run.run_id)
        assert [m.value for m in stored.metrics["acc"].get_all()] == [0.5]

    def test_a_model_with_a_tuple_hyperparameter_is_registered(self, registry, tmp_path):
        artifact = tmp_path / "a.bin"
        artifact.write_bytes(b"x")
        version = registry.register_model(
            name="mlp",
            artifact_path=str(artifact),
            artifact_type="model",
            framework="sklearn",
            hyperparameters={"hidden_layer_sizes": (50,), "n": np.int64(3)},
        )
        assert version.metadata.hyperparameters == {"hidden_layer_sizes": [50], "n": 3}


class TestVersionNumbersAreNeverReused:
    def test_deleting_the_newest_version_does_not_free_its_number(self, registry, tmp_path):
        v1 = _register(registry, tmp_path, b"1")
        v2 = _register(registry, tmp_path, b"2")
        registry.delete_model_version("m", v2.version)
        v3 = _register(registry, tmp_path, b"3")
        assert (v1.version, v2.version, v3.version) == (1, 2, 3)
        assert v3.model_id == v1.model_id

    def test_deleting_every_version_keeps_the_numbering_and_the_id(self, registry, tmp_path):
        v1 = _register(registry, tmp_path, b"1")
        registry.delete_model_version("m", v1.version)
        again = _register(registry, tmp_path, b"2")
        assert again.version == 2
        assert again.model_id == v1.model_id

    def test_a_registry_without_a_counter_learns_it_on_delete(self, registry, tmp_path, storage):
        _register(registry, tmp_path, b"1")
        v2 = _register(registry, tmp_path, b"2")
        storage.delete(registry._counters_path())  # a registry written before the counter
        registry.delete_model_version("m", v2.version)
        assert _register(registry, tmp_path, b"3").version == 3


class TestDatabricksLog:
    def test_the_storage_log_does_not_need_a_base_path(self):
        from types import SimpleNamespace

        from ducta.mlrun.config import _resolve_component_storage

        volume = SimpleNamespace(catalog="c", schema="s", volume_name="v")
        got = _resolve_component_storage(
            SimpleNamespace(), "Tracker", "tracking", "tracking_path", "x", None, volume, {}
        )
        assert got is volume


class TestRunArtifactsAndDeletion:
    def test_two_artifacts_of_a_run_keep_their_own_files(self, tracker, tmp_path):
        exp = tracker.create_experiment("e")
        run = tracker.start_run(experiment_id=exp.experiment_id, name="r")
        a, b = tmp_path / "a.txt", tmp_path / "b.txt"
        a.write_text("A")
        b.write_text("B")
        uri_a = tracker.log_artifact(run.run_id, str(a))
        uri_b = tracker.log_artifact(run.run_id, str(b))
        assert uri_a != uri_b
        out = tmp_path / "out"
        tracker.download_artifact(run.run_id, uri_a, str(out / "a.txt"))
        assert (out / "a.txt").read_text() == "A"

    def test_a_deleted_run_leaves_no_trace_in_a_metric_search(self, tracker):
        exp = tracker.create_experiment("e")
        ids = []
        for score in (0.9, 0.8):
            run = tracker.start_run(experiment_id=exp.experiment_id, name=f"r{score}")
            tracker.log_metric(run.run_id, "acc", score)
            tracker.end_run(run.run_id)
            ids.append(run.run_id)
        assert set(tracker.search_runs(exp.experiment_id, {"acc": (">", 0.5)})) == set(ids)

        tracker.delete_run(ids[0])

        assert tracker.search_runs(exp.experiment_id, {"acc": (">", 0.5)}) == [ids[1]]
        metrics_dir = tracker.storage._get_full_path(
            f"experiment_tracking/metrics/{exp.experiment_id}"
        )
        assert not list(metrics_dir.glob(f"{ids[0]}_metrics*"))


class TestIntegerRanges:
    def _config(self, **space):
        return HyperparamConfig.from_dict(
            {
                "algorithm": "random",
                "n_trials": 30,
                "objective": {"metric": "f1", "type": "maximize"},
                "search_space": space,
            }
        )

    def test_a_whole_number_range_samples_whole_numbers(self):
        search = RandomSearch(self._config(n={"min": 50, "max": 300}), seed=1)
        values = []
        while (params := search.ask()) is not None:
            values.append(params["n"])
        assert all(isinstance(v, int) and not isinstance(v, np.generic) for v in values)
        assert all(50 <= v <= 300 for v in values)

    def test_a_float_range_still_samples_floats(self):
        search = RandomSearch(self._config(lr={"min": 0.01, "max": 0.5}), seed=1)
        assert isinstance(search.ask()["lr"], float)

    def test_step_and_log_are_honoured(self):
        stepped = IntegerRange(10, 50, step=10)
        assert {stepped.rvs(random_state=i) for i in range(100)} <= {10, 20, 30, 40, 50}
        logged = IntegerRange(1, 1000, log=True)
        sample = [logged.rvs(random_state=i) for i in range(300)]
        assert all(1 <= v <= 1000 for v in sample)
        assert sum(v < 32 for v in sample) > 100  # log-uniform leans low

    def test_the_distribution_works_with_randomized_search_cv(self):
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import RandomizedSearchCV

        rng = np.random.default_rng(0)
        x = rng.normal(size=(60, 2))
        y = (x[:, 0] > 0).astype(int)
        space = self._config(n_estimators={"min": 2, "max": 6}).build_distributions()
        search = RandomizedSearchCV(
            RandomForestClassifier(random_state=0), space, n_iter=3, cv=2, random_state=0
        )
        search.fit(x, y)
        assert isinstance(search.best_params_["n_estimators"], int)


class TestStorageExtensions:
    def test_a_suffixless_path_is_found_by_every_operation(self, storage):
        storage.write_json({"a": 1}, "foo")
        assert storage.exists("foo")
        assert storage.read_json("foo") == {"a": 1}
        storage.write_dataframe(pd.DataFrame({"x": [1]}), "frame")
        assert storage.read_dataframe("frame")["x"].tolist() == [1]
        storage.delete("foo")
        assert not storage.exists("foo")

    def test_a_missing_path_is_still_missing(self, storage):
        assert not storage.exists("nope")
        with pytest.raises(FileNotFoundError):
            storage.read_json("nope")


class TestBinaryMetricsWithAnyLabels:
    @pytest.mark.parametrize("labels", [("no", "yes"), (0, 2), (-1, 3)])
    def test_the_greater_label_is_the_positive_class(self, labels):
        from sklearn.linear_model import LogisticRegression

        from ducta.mlrun.training import _evaluate

        rng = np.random.default_rng(0)
        x = rng.normal(size=(80, 2))
        y = np.where(x[:, 0] > 0, labels[1], labels[0])
        model = LogisticRegression().fit(x, y)
        scores = _evaluate(model, x, y, "classification")
        assert scores["f1"] > 0.8 and 0.5 < scores["auc_roc"] <= 1.0


class TestDeadLockOwner:
    def test_a_fresh_lock_of_a_dead_process_is_taken_at_once(self, tmp_path):
        from tests.mlrun.test_concurrency import _find_unused_pid

        path = tmp_path / "x.lock"
        path.write_text(
            json.dumps(
                {
                    "pid": _find_unused_pid(),
                    "host": socket.gethostname(),
                    "acquired_at": time.time(),
                    "token": "orphan",
                }
            )
        )
        started = time.time()
        lock = FileLock(path, timeout=5.0)
        assert lock.acquire() is True
        assert time.time() - started < 2.0
        lock.release()

    def test_a_fresh_lock_of_another_host_still_waits(self, tmp_path):
        path = tmp_path / "x.lock"
        path.write_text(
            json.dumps(
                {"pid": 1, "host": "elsewhere", "acquired_at": time.time(), "token": "remote"}
            )
        )
        assert FileLock(path, timeout=0.3).acquire() is False
        assert os.path.exists(path)


def test_write_dataframe_keeps_its_retry_and_the_path_helper_has_none():
    # Inserting _resolve_existing under the decorator moved the retry off write_dataframe.
    assert hasattr(LocalStorageBackend.write_dataframe, "__wrapped__")
    assert not hasattr(LocalStorageBackend._resolve_existing, "__wrapped__")


def test_a_float_max_makes_a_float_range():
    config = HyperparamConfig(algorithm="random", search_space={"x": {"min": 1, "max": 1.5}})
    assert not config._is_int_range(config.search_space["x"])


def test_whole_endpoints_stay_a_whole_number_range():
    config = HyperparamConfig(algorithm="random", search_space={"n": {"min": 50, "max": 300}})
    assert config._is_int_range(config.search_space["n"])


@pytest.mark.parametrize(
    "spec", [{"min": 0, "max": 10, "log": True}, {"min": 0.0, "max": 1.0, "log": True}]
)
def test_a_log_range_from_zero_is_refused_up_front(spec):
    from ducta.mlrun.hyperparams import HyperparamConfigError

    with pytest.raises(HyperparamConfigError, match="log range"):
        HyperparamConfig(algorithm="random", search_space={"x": spec})
