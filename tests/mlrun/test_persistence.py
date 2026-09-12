"""Unit tests for ducta.mlrun.persistence (infer_schema, persist_model)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ducta.mlrun.persistence import infer_schema, persist_model


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
