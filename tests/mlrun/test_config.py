"""Unit tests for ducta.mlrun.config (MLOpsConfig + backend resolution)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ducta.mlrun.config import (
    MLOpsConfig,
    MLOpsContext,
    StorageBackendFactory,
    _resolve_backend_type,
)


class TestMLOpsConfigValidate:
    def test_defaults_valid(self):
        MLOpsConfig().validate()  # no raise

    def test_bad_backend_type(self):
        with pytest.raises(ValueError, match="Invalid backend_type"):
            MLOpsConfig(backend_type="quantum").validate()  # type: ignore[arg-type]

    def test_max_active_runs_min(self):
        with pytest.raises(ValueError, match="max_active_runs"):
            MLOpsConfig(max_active_runs=0).validate()

    def test_negative_retries(self):
        with pytest.raises(ValueError, match="max_retries"):
            MLOpsConfig(max_retries=-1).validate()

    def test_zero_model_retention_days_raises(self):
        with pytest.raises(ValueError, match="model_retention_days"):
            MLOpsConfig(model_retention_days=0).validate()

    def test_zero_max_versions_per_model_raises(self):
        with pytest.raises(ValueError, match="max_versions_per_model"):
            MLOpsConfig(max_versions_per_model=0).validate()

    def test_zero_metric_buffer_size_raises(self):
        with pytest.raises(ValueError, match="metric_buffer_size"):
            MLOpsConfig(metric_buffer_size=0).validate()

    def test_negative_retry_delay_raises(self):
        with pytest.raises(ValueError, match="retry_delay"):
            MLOpsConfig(retry_delay=-1.0).validate()

    def test_negative_stale_run_age_raises(self):
        with pytest.raises(ValueError, match="stale_run_age_seconds"):
            MLOpsConfig(stale_run_age_seconds=-1.0).validate()


class TestResolveBackendType:
    def test_distributed_is_databricks(self):
        assert _resolve_backend_type("distributed") == "databricks"

    def test_local(self):
        assert _resolve_backend_type("local") == "local"

    def test_none_defaults_local(self):
        assert _resolve_backend_type(None) == "local"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown backend_type"):
            _resolve_backend_type("weird")  # type: ignore[arg-type]


class TestFromEnv:
    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv("Ducta_MLOPS_BACKEND", "local")
        monkeypatch.setenv("Ducta_MLOPS_PATH", "/custom/mlops")
        cfg = MLOpsConfig.from_env()
        assert cfg.backend_type == "local"
        assert cfg.storage_path == "/custom/mlops"


class TestResolveMLOpsPath:
    def _ctx(self, **kw):
        base = dict(global_config={}, output_path=None, env=None, execution_mode="local")
        base.update(kw)
        return SimpleNamespace(**base)

    def test_explicit_base_path_wins(self):
        ctx = self._ctx(output_path="/out")
        assert StorageBackendFactory._resolve_mlops_path(ctx, base_path="/explicit") == "/explicit"

    def test_global_config_mlops_path(self):
        ctx = self._ctx(global_config={"mlops_path": "/gs/path"})
        assert StorageBackendFactory._resolve_mlops_path(ctx) == "/gs/path"

    def test_output_path_with_pipeline_and_env(self):
        ctx = self._ctx(output_path="/out", env="dev")
        got = StorageBackendFactory._resolve_mlops_path(ctx, pipeline_name="sales.train")
        assert got == "/out/dev/sales/train"

    def test_output_path_only(self):
        ctx = self._ctx(output_path="/out", env="dev")
        assert StorageBackendFactory._resolve_mlops_path(ctx) == "/out/dev"

    def test_no_path_returns_none(self):
        ctx = self._ctx(output_path=None)
        assert StorageBackendFactory._resolve_mlops_path(ctx) is None

    def test_empty_mlops_path_falls_through_to_output_path(self):
        # A `mlops_path: ""` (e.g. from a templated config) must not be
        # returned as-is — that would make LocalStorageBackend write into the
        # current working directory instead of falling through to output_path.
        ctx = self._ctx(global_config={"mlops_path": ""}, output_path="/out", env="dev")
        assert StorageBackendFactory._resolve_mlops_path(ctx) == "/out/dev"


class TestEnvBoolAcceptsCommonSpellings:
    """_env_bool used to only recognize the literal "true"; a plausible
    Ducta_MLOPS_ENABLE_RETRY=1 silently became False with no warning."""

    @pytest.mark.parametrize("raw", ["true", "yes", "on", "1", "TRUE", "On"])
    def test_true_spellings(self, monkeypatch, raw):
        monkeypatch.setenv("Ducta_MLOPS_ENABLE_RETRY", raw)
        assert MLOpsConfig._env_bool("Ducta_MLOPS_ENABLE_RETRY", False) is True

    @pytest.mark.parametrize("raw", ["false", "no", "off", "0"])
    def test_false_spellings(self, monkeypatch, raw):
        monkeypatch.setenv("Ducta_MLOPS_ENABLE_RETRY", raw)
        assert MLOpsConfig._env_bool("Ducta_MLOPS_ENABLE_RETRY", True) is False

    def test_unrecognized_value_falls_back_to_default_with_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("Ducta_MLOPS_ENABLE_RETRY", "maybe")
        assert MLOpsConfig._env_bool("Ducta_MLOPS_ENABLE_RETRY", True) is True


class TestFromContextConfigWiring:
    """MLOpsContext.from_context() used to ignore MLOpsConfig entirely — every
    Ducta_MLOPS_* env var and every field on a caller-built MLOpsConfig had no
    effect on the path a real pipeline run actually takes."""

    def _ctx(self, tmp_path):
        return SimpleNamespace(
            global_config={},
            output_path=str(tmp_path / "output"),
            env="dev",
            execution_mode="local",
        )

    def test_explicit_kwarg_wins_over_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("Ducta_MLOPS_MAX_ACTIVE_RUNS", "3")
        ctx = self._ctx(tmp_path)
        mlops_ctx = MLOpsContext.from_context(ctx, max_active_runs=2, pipeline_name="sales.train")
        assert mlops_ctx.experiment_tracker.max_active_runs == 2

    def test_env_var_takes_effect_without_explicit_kwarg(self, tmp_path, monkeypatch):
        monkeypatch.setenv("Ducta_MLOPS_MAX_ACTIVE_RUNS", "3")
        ctx = self._ctx(tmp_path)
        mlops_ctx = MLOpsContext.from_context(ctx, pipeline_name="sales.train")
        assert mlops_ctx.experiment_tracker.max_active_runs == 3

    def test_config_is_attached(self, tmp_path):
        ctx = self._ctx(tmp_path)
        mlops_ctx = MLOpsContext.from_context(ctx, pipeline_name="sales.train")
        assert mlops_ctx.config is not None
        assert mlops_ctx.config.max_active_runs == mlops_ctx.experiment_tracker.max_active_runs

    def test_retry_classification_preserved_for_missing_index(self, tmp_path):
        """A bare RetryConfig() defaults non_retryable_exceptions=() empty,
        and FileNotFoundError *is* an OSError subclass — so building the
        per-context retry_config from scratch instead of from
        STORAGE_RETRY_CONFIG would make "index file doesn't exist yet" (a
        normal outcome _load_experiments_index's own except FileNotFoundError
        relies on) retry 3x and surface as RetryExhaustedError instead."""
        ctx = self._ctx(tmp_path)
        mlops_ctx = MLOpsContext.from_context(ctx, pipeline_name="sales.train")
        # No experiment/run ever created, so the runs index parquet does not
        # exist — list_experiments() must return [] via the FileNotFoundError
        # fallback, not raise.
        assert mlops_ctx.experiment_tracker.list_experiments() == []


class TestMLOpsContextSharedStorage:
    def _ctx(self, tmp_path):
        return SimpleNamespace(
            global_config={},
            output_path=str(tmp_path / "output"),
            env="dev",
            execution_mode="local",
        )

    def test_from_context_shares_one_storage_backend(self, tmp_path):
        ctx = self._ctx(tmp_path)
        mlops_ctx = MLOpsContext.from_context(ctx, pipeline_name="sales.train")
        assert mlops_ctx.model_registry is not None
        assert mlops_ctx.experiment_tracker is not None
        assert mlops_ctx.model_registry.storage is mlops_ctx.experiment_tracker.storage


class TestMLOpsContextMixedKwargsWarning:
    def test_warns_when_legacy_and_modern_kwargs_both_given(self, tmp_path, caplog):
        from ducta.mlrun.experiment_tracking import ExperimentTracker
        from ducta.mlrun.storage import LocalStorageBackend

        storage = LocalStorageBackend(base_path=str(tmp_path), enable_circuit_breaker=False)
        tracker = ExperimentTracker(storage=storage)

        warned = []
        import ducta.mlrun.config as config_module

        orig_warning = config_module.logger.warning

        def capture(*args, **kwargs):
            warned.append((args, kwargs))
            return orig_warning(*args, **kwargs)

        import unittest.mock as mock

        with mock.patch.object(config_module.logger, "warning", side_effect=capture):
            MLOpsContext(
                experiment_tracker=tracker, backend_type="local", storage_path=str(tmp_path)
            )

        assert len(warned) == 1
