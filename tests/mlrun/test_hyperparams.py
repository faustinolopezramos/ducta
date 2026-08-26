"""Unit tests for ducta.mlrun.hyperparams."""

from __future__ import annotations

import pytest

from ducta.mlrun.hyperparams import (
    HyperparamConfig,
    HyperparamConfigError,
    SweepLimitError,
    expand_sweep_grid,
    load_hyperparams_config,
)


class TestHyperparamConfig:
    def test_defaults(self):
        cfg = HyperparamConfig(algorithm="grid")
        assert cfg.algorithm == "grid"
        assert cfg.cv_folds == 5
        assert cfg.n_trials == 1  # grid default

    def test_random_default_trials(self):
        assert HyperparamConfig(algorithm="random").n_trials == 30

    def test_invalid_algorithm(self):
        with pytest.raises(HyperparamConfigError):
            HyperparamConfig(algorithm="genetic")

    def test_from_dict(self):
        cfg = HyperparamConfig.from_dict({"algorithm": "random", "cv_folds": 3})
        assert cfg.algorithm == "random"
        assert cfg.cv_folds == 3


class TestStoragePrunerStudyName:
    """storage=/pruner=/study_name= are all opt-in — omitted, they leave the
    pre-existing behavior (in-memory study, Optuna's own default pruner,
    fresh study every run) completely unchanged."""

    def test_defaults_are_none(self):
        cfg = HyperparamConfig(algorithm="grid")
        assert cfg.storage is None
        assert cfg.pruner is None
        assert cfg.study_name is None

    def test_from_dict_reads_all_three(self):
        cfg = HyperparamConfig.from_dict(
            {
                "algorithm": "bayesian",
                "search_space": {"lr": [0.1, 0.2]},
                "storage": "sqlite:///study.db",
                "pruner": "median",
                "study_name": "my-study",
            }
        )
        assert cfg.storage == "sqlite:///study.db"
        assert cfg.pruner == "median"
        assert cfg.study_name == "my-study"

    def test_unknown_pruner_raises(self):
        with pytest.raises(HyperparamConfigError, match="Unknown pruner"):
            HyperparamConfig(algorithm="bayesian", search_space={"lr": [0.1, 0.2]}, pruner="nope")

    def test_explicit_none_pruner_is_a_distinct_valid_value(self):
        # "none" (string) means "guarantee no pruning" and is distinct from
        # not declaring pruner at all (None) — see search.OptunaSearch._build_pruner.
        cfg = HyperparamConfig(algorithm="grid", pruner="none")
        assert cfg.pruner == "none"

    def test_pruner_case_insensitive(self):
        cfg = HyperparamConfig(algorithm="grid", pruner="MEDIAN")
        assert cfg.pruner == "median"


class TestExpandSweepGrid:
    def test_cartesian(self):
        combos = expand_sweep_grid({"lr": [0.1, 0.2], "n": [10]})
        assert len(combos) == 2

    def test_scalar_only(self):
        assert expand_sweep_grid({"lr": 0.1}) == [{"lr": 0.1}]

    def test_empty_list_raises(self):
        with pytest.raises(SweepLimitError, match="empty list"):
            expand_sweep_grid({"lr": []})

    def test_limit_exceeded(self):
        with pytest.raises(SweepLimitError):
            expand_sweep_grid({"a": list(range(10)), "b": list(range(10))}, max_runs=5)


class TestFrangeIncludesUpperBound:
    def test_upper_bound_included_despite_float_rounding(self):
        cfg = HyperparamConfig(
            algorithm="grid",
            search_space={"lr": {"min": 0.0, "max": 0.3, "step": 0.1}},
        )
        grid = cfg.build_param_grid()
        assert grid["lr"] == [0.0, 0.1, 0.2, 0.3]

    def test_upper_bound_included_non_aligned_start(self):
        cfg = HyperparamConfig(
            algorithm="grid",
            search_space={"lr": {"min": 0.05, "max": 0.35, "step": 0.05}},
        )
        grid = cfg.build_param_grid()
        assert grid["lr"][-1] == 0.35


class TestBuildDistributionsScipyGuard:
    def test_missing_scipy_raises_actionable_error(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "scipy.stats" or name.startswith("scipy"):
                raise ImportError("No module named 'scipy'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        cfg = HyperparamConfig(
            algorithm="random",
            search_space={"lr": {"min": 0.0, "max": 1.0}},
        )
        with pytest.raises(HyperparamConfigError, match="scipy"):
            cfg.build_distributions()


class TestLoadHyperparamsConfig:
    def test_dict_single_key(self):
        cfg = load_hyperparams_config({"train": {"algorithm": "grid", "cv_folds": 4}})
        assert cfg is not None
        assert cfg.cv_folds == 4

    def test_explicit_pipeline_key(self):
        data = {"p1": {"algorithm": "grid"}, "p2": {"algorithm": "random"}}
        cfg = load_hyperparams_config(data, pipeline_key="p2")
        assert cfg.algorithm == "random"

    def test_multi_key_without_key_returns_none(self):
        data = {"p1": {"algorithm": "grid"}, "p2": {"algorithm": "random"}}
        assert load_hyperparams_config(data) is None

    def test_empty_returns_none(self):
        assert load_hyperparams_config({}) is None
