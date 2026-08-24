"""Unit tests for ducta.mlrun.validators.ArtifactValidator's trust boundary.

Loading a pickle/joblib artifact to "validate" it means executing it. These
tests confirm that ArtifactValidator only deserializes pickle-based
artifacts when the caller explicitly opts in via trust_artifact_source, and
that PyTorch loads always pass weights_only=True regardless of that flag.
"""

from __future__ import annotations

import pickle
import sys
import types
from unittest.mock import MagicMock

import pytest

from ducta.mlrun.model_registry import ModelRegistry
from ducta.mlrun.storage import LocalStorageBackend
from ducta.mlrun.validators import ArtifactValidator, ValidationError

_EXECUTED = {"flag": False}


def _mark_executed():
    _EXECUTED["flag"] = True
    return "executed"


class _Payload:
    """Pickles to a callable that flips _EXECUTED — proof of code execution."""

    def __reduce__(self):
        return (_mark_executed, ())


@pytest.fixture(autouse=True)
def _reset_executed_flag():
    _EXECUTED["flag"] = False
    yield
    _EXECUTED["flag"] = False


class TestPickleBasedFrameworksRequireTrust:
    def test_default_does_not_deserialize_pickle(self, tmp_path):
        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(pickle.dumps(_Payload()))

        ArtifactValidator.validate_artifact(str(artifact), framework="sklearn")

        assert _EXECUTED["flag"] is False

    def test_trust_artifact_source_true_deserializes_pickle(self, tmp_path):
        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(pickle.dumps(_Payload()))

        ArtifactValidator.validate_artifact(
            str(artifact), framework="sklearn", trust_artifact_source=True
        )

        assert _EXECUTED["flag"] is True

    def test_joblib_and_custom_frameworks_also_default_to_untrusted(self, tmp_path):
        for framework in ("joblib", "custom", "pickle"):
            _EXECUTED["flag"] = False
            artifact = tmp_path / f"model_{framework}.pkl"
            artifact.write_bytes(pickle.dumps(_Payload()))

            ArtifactValidator.validate_artifact(str(artifact), framework=framework)

            assert _EXECUTED["flag"] is False, f"{framework} deserialized without trust"

    def test_lightweight_validation_rejects_empty_artifact(self, tmp_path):
        artifact = tmp_path / "empty.pkl"
        artifact.write_bytes(b"")

        with pytest.raises(ValidationError):
            ArtifactValidator.validate_artifact(str(artifact), framework="sklearn")

    def test_xgboost_native_json_format_is_always_loaded_without_pickle(self, tmp_path):
        # The .json path is xgboost's native (non-pickle) format — it should
        # not require trust_artifact_source, and it never touches pickle.
        fake_xgb = types.SimpleNamespace(Booster=MagicMock(return_value=object()))
        artifact = tmp_path / "model.json"
        artifact.write_text("{}")

        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "xgboost", fake_xgb)
            ArtifactValidator.validate_artifact(str(artifact), framework="xgboost")

        fake_xgb.Booster.assert_called_once()
        assert _EXECUTED["flag"] is False

    def test_xgboost_pickle_fallback_requires_trust(self, tmp_path):
        fake_xgb = types.SimpleNamespace(Booster=MagicMock())
        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(pickle.dumps(_Payload()))

        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "xgboost", fake_xgb)
            ArtifactValidator.validate_artifact(str(artifact), framework="xgboost")
            assert _EXECUTED["flag"] is False

            ArtifactValidator.validate_artifact(
                str(artifact), framework="xgboost", trust_artifact_source=True
            )
            assert _EXECUTED["flag"] is True


class TestPytorchAlwaysUsesWeightsOnly:
    def test_torch_load_is_called_with_weights_only_true(self, tmp_path):
        fake_torch = types.SimpleNamespace(load=MagicMock(return_value={"state": 1}))
        artifact = tmp_path / "model.pt"
        artifact.write_bytes(b"fake-weights")

        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "torch", fake_torch)
            # trust_artifact_source is irrelevant to pytorch — weights_only
            # is the mitigation, applied unconditionally.
            ArtifactValidator.validate_artifact(str(artifact), framework="pytorch")

        fake_torch.load.assert_called_once()
        _, kwargs = fake_torch.load.call_args
        assert kwargs.get("weights_only") is True


class TestRegisterModelDefaultsToUntrusted:
    def test_register_model_default_does_not_execute_pickle_payload(self, tmp_path):
        storage = LocalStorageBackend(
            base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False
        )
        registry = ModelRegistry(storage=storage, registry_path="model_registry")

        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(pickle.dumps(_Payload()))

        version = registry.register_model(
            name="my-model",
            artifact_path=str(artifact),
            artifact_type="model",
            framework="sklearn",
        )

        assert version is not None
        assert _EXECUTED["flag"] is False

    def test_register_model_with_trust_flag_executes_pickle_payload(self, tmp_path):
        storage = LocalStorageBackend(
            base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False
        )
        registry = ModelRegistry(storage=storage, registry_path="model_registry")

        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(pickle.dumps(_Payload()))

        registry.register_model(
            name="my-model",
            artifact_path=str(artifact),
            artifact_type="model",
            framework="sklearn",
            trust_artifact_source=True,
        )

        assert _EXECUTED["flag"] is True
