"""Unit tests for ducta.mlrun.persistence (infer_schema, persist_model)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.mlrun.persistence import infer_schema, log_run_metrics, persist_model


class _FakeDataFrame:
    def __init__(self, columns, dtypes):
        self.columns = columns
        self.dtypes = dtypes


class _FakeSeries:
    def __init__(self, name, dtype):
        self.name = name
        self.dtypes = dtype


class TestInferSchema:
    def test_none_input(self):
        assert infer_schema(None) is None

    def test_dataframe_like(self):
        df = _FakeDataFrame(columns=["a", "b"], dtypes=["int64", "object"])
        assert infer_schema(df) == {"a": "int64", "b": "object"}

    def test_series_like_uses_name(self):
        series = _FakeSeries(name="target", dtype="float64")
        assert infer_schema(series) == {"target": "float64"}

    def test_series_like_without_name_falls_back(self):
        series = SimpleNamespace(dtypes="float64")
        assert infer_schema(series) == {"target": "float64"}

    def test_unusable_object_returns_none(self):
        class _Broken:
            @property
            def columns(self):
                raise RuntimeError("boom")

        assert infer_schema(_Broken()) is None


class TestPersistModel:
    def test_without_registry_writes_local_versioned_file(self, tmp_path):
        ml_context = SimpleNamespace(mlops_context=None, mlops_run_id="run123", model_version=None)
        base_dir = tmp_path / "models"

        result = persist_model(
            {"weights": [1, 2, 3]},
            ml_context,
            "my_model",
            base_dir=str(base_dir),
        )

        dest_dir = base_dir / "my_model" / "run123"
        assert (dest_dir / "model.pkl").exists()
        pointer = base_dir / "my_model" / "latest.txt"
        assert pointer.exists()
        assert Path(pointer.read_text().strip()) == (dest_dir / "model.pkl").resolve()
        assert result["version"] == "run123"
        assert result["artifact_uri"] == (dest_dir / "model.pkl").resolve().as_uri()

    def test_with_registry_uses_registered_version(self, tmp_path):
        registered = SimpleNamespace(version=3, artifact_uri="s3://bucket/my_model/v3/model.pkl")

        class _FakeRegistry:
            def register_model(self, **kwargs):
                self.kwargs = kwargs
                return registered

        registry = _FakeRegistry()
        mlops_context = SimpleNamespace(model_registry=registry)
        ml_context = SimpleNamespace(
            mlops_context=mlops_context, mlops_run_id="run456", model_version=None
        )

        result = persist_model({"weights": [1, 2, 3]}, ml_context, "my_model")

        assert result == {"artifact_uri": registered.artifact_uri, "version": 3}
        assert registry.kwargs["name"] == "my_model"
        assert registry.kwargs["experiment_run_id"] == "run456"

    def test_registry_failure_falls_back_to_local_file(self, tmp_path):
        class _FailingRegistry:
            def register_model(self, **kwargs):
                raise RuntimeError("registry unavailable")

        mlops_context = SimpleNamespace(model_registry=_FailingRegistry())
        ml_context = SimpleNamespace(
            mlops_context=mlops_context, mlops_run_id="run789", model_version=None
        )
        base_dir = tmp_path / "models"

        result = persist_model(
            {"weights": [1, 2, 3]},
            ml_context,
            "my_model",
            base_dir=str(base_dir),
        )

        dest_dir = base_dir / "my_model" / "run789"
        assert (dest_dir / "model.pkl").exists()
        assert result["version"] == "run789"


class TestLocalVersionIsUnique:
    """With tracking off a context carries no run id and ``model_version == "unknown"``."""

    @staticmethod
    def _persist(base_dir, **context):
        ml_context = SimpleNamespace(mlops_context=None, **context)
        return persist_model({"w": 1}, ml_context, "my_model", base_dir=str(base_dir))

    def test_unknown_version_never_names_the_directory(self, tmp_path):
        result = self._persist(tmp_path, mlops_run_id=None, model_version="unknown")

        assert result["version"] != "unknown"
        assert not (tmp_path / "my_model" / "unknown").exists()
        assert (tmp_path / "my_model" / result["version"] / "model.pkl").exists()

    def test_two_runs_keep_two_models_and_latest_points_to_the_newer(self, tmp_path):
        first = self._persist(tmp_path, mlops_run_id=None, model_version="unknown")
        second = self._persist(tmp_path, mlops_run_id=None, model_version="unknown")

        assert first["version"] != second["version"]
        assert (tmp_path / "my_model" / first["version"] / "model.pkl").exists()
        assert (tmp_path / "my_model" / second["version"] / "model.pkl").exists()
        pointer = (tmp_path / "my_model" / "latest.txt").read_text().strip()
        assert Path(pointer).parent.name == second["version"]

    def test_a_fixed_label_is_suffixed_so_it_cannot_overwrite_itself(self, tmp_path):
        first = self._persist(tmp_path, mlops_run_id=None, model_version="v1")
        second = self._persist(tmp_path, mlops_run_id=None, model_version="v1")

        assert first["version"].startswith("v1-")
        assert first["version"] != second["version"]

    def test_placeholder_run_id_is_ignored(self, tmp_path):
        result = self._persist(tmp_path, mlops_run_id="None", model_version=None)

        assert result["version"].lower() != "none"

    def test_path_separators_in_a_label_do_not_escape_the_model_directory(self, tmp_path):
        result = self._persist(tmp_path, mlops_run_id="../evil/run", model_version=None)

        assert "/" not in result["version"] and ".." not in Path(result["version"]).parts
        assert (tmp_path / "my_model" / result["version"] / "model.pkl").exists()


class TestNativeFormat:
    """``native=True`` writes xgboost/lightgbm in their own format, which loads without
    unpickling anything — so scoring it does not need ``model.trust_artifact``."""

    @staticmethod
    def _context(**extra):
        return SimpleNamespace(mlops_context=None, mlops_run_id="run1", model_version=None, **extra)

    def test_default_is_still_a_pickle(self, tmp_path):
        xgb = pytest.importorskip("xgboost")
        model = xgb.XGBClassifier(n_estimators=2).fit([[0.0], [1.0], [2.0], [3.0]], [0, 0, 1, 1])

        persist_model(model, self._context(), "m", framework="xgboost", base_dir=str(tmp_path))

        assert (tmp_path / "m" / "run1" / "model.pkl").exists()
        assert not (tmp_path / "m" / "run1" / "model.json").exists()

    def test_xgboost_native_round_trips_through_a_booster(self, tmp_path):
        xgb = pytest.importorskip("xgboost")
        X, y = [[0.0], [1.0], [2.0], [3.0]], [0, 0, 1, 1]
        model = xgb.XGBClassifier(n_estimators=3).fit(X, y)

        result = persist_model(
            model, self._context(), "m", framework="xgboost", base_dir=str(tmp_path), native=True
        )

        artifact = tmp_path / "m" / "run1" / "model.json"
        assert artifact.exists() and not (tmp_path / "m" / "run1" / "model.pkl").exists()
        assert result["artifact_uri"] == artifact.resolve().as_uri()
        assert Path((tmp_path / "m" / "latest.txt").read_text()) == artifact.resolve()
        booster = xgb.Booster()
        booster.load_model(str(artifact))
        assert list(booster.predict(xgb.DMatrix([[0.0], [3.0]]))) == pytest.approx(
            list(model.predict_proba([[0.0], [3.0]])[:, 1]), abs=1e-6
        )

    def test_lightgbm_native_saves_the_wrapped_booster(self, tmp_path):
        class _Booster:
            def save_model(self, path):
                Path(path).write_text("tree\n")

        wrapper = SimpleNamespace(booster_=_Booster())

        persist_model(
            wrapper, self._context(), "m", framework="lightgbm", base_dir=str(tmp_path), native=True
        )

        assert (tmp_path / "m" / "run1" / "model.txt").read_text() == "tree\n"

    def test_native_for_a_framework_without_one_falls_back_to_a_pickle(self, tmp_path):
        persist_model(
            {"w": 1}, self._context(), "m", framework="sklearn", base_dir=str(tmp_path), native=True
        )

        assert (tmp_path / "m" / "run1" / "model.pkl").exists()

    def test_registry_receives_the_native_file_and_its_type(self, tmp_path):
        xgb = pytest.importorskip("xgboost")
        model = xgb.XGBClassifier(n_estimators=2).fit([[0.0], [1.0], [2.0], [3.0]], [0, 0, 1, 1])
        seen = {}

        class _Registry:
            def register_model(self, **kwargs):
                seen.update(kwargs, existed=Path(kwargs["artifact_path"]).exists())
                return SimpleNamespace(version=1, artifact_uri="x://m/1")

        context = SimpleNamespace(
            mlops_context=SimpleNamespace(model_registry=_Registry()),
            mlops_run_id="run1",
            model_version=None,
        )

        persist_model(model, context, "m", framework="xgboost", native=True)

        assert seen["artifact_path"].endswith("m.json")
        assert seen["artifact_type"] == "xgboost"
        assert seen["existed"] is True


class _FakeTracker:
    def __init__(self, fail_on=()):
        self.logged = []
        self._fail_on = fail_on

    def log_metric(self, run_id, key, value):
        if key in self._fail_on:
            raise ValueError("NaN")
        self.logged.append((run_id, key, value))


def _tracked(tracker, registry=None):
    mlops = SimpleNamespace(experiment_tracker=tracker, model_registry=registry)
    return SimpleNamespace(mlops_context=mlops, mlops_run_id="run-1", model_version=None)


class TestMetricsReachTheRun:
    """`persist_model(metrics=...)` used to feed the registry only, leaving the run with
    no metrics: `ducta experiment show` printed "(none)" and a sweep could not be ranked."""

    def test_persist_model_logs_its_metrics_to_the_tracked_run(self, tmp_path):
        tracker = _FakeTracker()

        persist_model(
            {"w": 1},
            _tracked(tracker),
            "m",
            metrics={"val_auc": 0.9, "test_f1": 0.7},
            base_dir=str(tmp_path),
        )

        assert tracker.logged == [("run-1", "val_auc", 0.9), ("run-1", "test_f1", 0.7)]

    def test_log_to_run_false_leaves_the_run_alone(self, tmp_path):
        tracker = _FakeTracker()

        persist_model(
            {"w": 1},
            _tracked(tracker),
            "m",
            metrics={"val_auc": 0.9},
            base_dir=str(tmp_path),
            log_to_run=False,
        )

        assert tracker.logged == []

    def test_a_bad_metric_is_skipped_and_the_rest_are_logged(self):
        tracker = _FakeTracker(fail_on=("bad",))

        log_run_metrics(_tracked(tracker), {"bad": float("nan"), "good": 0.5, "text": "x"})

        assert tracker.logged == [("run-1", "good", 0.5)]

    def test_a_boolean_is_not_a_metric(self):
        tracker = _FakeTracker()

        log_run_metrics(_tracked(tracker), {"flag": True, "n": 3})

        assert tracker.logged == [("run-1", "n", 3)]

    def test_without_a_tracked_run_nothing_happens(self, tmp_path):
        ml_context = SimpleNamespace(mlops_context=None, mlops_run_id=None, model_version=None)

        persist_model({"w": 1}, ml_context, "m", metrics={"a": 1.0}, base_dir=str(tmp_path))
        log_run_metrics(None, {"a": 1.0})  # no context at all

    def test_the_registry_still_receives_the_metrics(self):
        registered = SimpleNamespace(version=1, artifact_uri="x")

        class _Registry:
            def register_model(self, **kwargs):
                self.kwargs = kwargs
                return registered

        registry = _Registry()
        persist_model({"w": 1}, _tracked(_FakeTracker(), registry), "m", metrics={"a": 1.0})

        assert registry.kwargs["metrics"] == {"a": 1.0}
