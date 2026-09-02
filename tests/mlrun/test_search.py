"""Unit tests for ducta.mlrun.search — the search strategies that drive HPO.

HyperparamConfig could already build sklearn grids, scipy distributions and an
Optuna space, but nothing in the engine ever called any of it: the only search
that ran was a flat cartesian product with no random/Bayesian option and no way
to honor n_trials. These pin the strategies that close that gap.
"""

from __future__ import annotations

import math

import pytest

from ducta.mlrun.hyperparams import HyperparamConfig, HyperparamConfigError
from ducta.mlrun.search import (
    GridSearch,
    OptunaSearch,
    RandomSearch,
    SearchError,
    build_search_strategy,
    resolve_objective,
)


def _config(**overrides):
    data = {
        "algorithm": "grid",
        "objective": {"metric": "val_f1", "type": "maximize"},
        "search_space": {"depth": [3, 5], "n_estimators": [10, 20]},
    }
    data.update(overrides)
    return HyperparamConfig.from_dict(data)


def _drain(strategy):
    """Every set the strategy proposes, until it says it is done."""
    proposals = []
    while True:
        params = strategy.ask()
        if params is None:
            return proposals
        proposals.append(params)


class TestGridSearch:
    def test_expands_full_cartesian_product(self):
        proposals = _drain(build_search_strategy(_config()))
        assert len(proposals) == 4
        assert {tuple(sorted(p.items())) for p in proposals} == {
            (("depth", 3), ("n_estimators", 10)),
            (("depth", 3), ("n_estimators", 20)),
            (("depth", 5), ("n_estimators", 10)),
            (("depth", 5), ("n_estimators", 20)),
        }

    def test_conditional_params_never_produce_invalid_combinations(self):
        """A flat product over the union of values would pair lbfgs with l1.

        build_param_grid returns one sub-grid per parent value, and each is
        expanded separately, so only declared parent/child pairings appear.
        """
        config = _config(
            search_space={
                "solver": ["saga", "lbfgs"],
                "penalty": {
                    "depends_on": {
                        "param": "solver",
                        "mapping": {"saga": ["l1", "l2"], "lbfgs": ["l2"]},
                    }
                },
            }
        )
        proposals = _drain(build_search_strategy(config))

        assert len(proposals) == 3  # not 4: lbfgs+l1 is not declared
        assert all(p["penalty"] == "l2" for p in proposals if p["solver"] == "lbfgs")

    def test_refuses_a_grid_over_the_trial_cap(self):
        config = _config(search_space={f"p{i}": [1, 2, 3] for i in range(5)})  # 243 combos
        with pytest.raises(SearchError, match="over the limit"):
            GridSearch(config, max_trials=50)


class TestRandomSearch:
    def test_honors_the_trial_budget(self):
        config = _config(algorithm="random", n_trials=7)
        assert len(_drain(build_search_strategy(config))) == 7

    def test_explicit_n_trials_overrides_the_config(self):
        config = _config(algorithm="random", n_trials=30)
        assert len(_drain(build_search_strategy(config, n_trials=3))) == 3

    def test_same_seed_reproduces_the_same_proposals(self):
        config = _config(
            algorithm="random",
            n_trials=5,
            search_space={"lr": {"min": 1e-4, "max": 1e-1, "log": True}},
        )
        first = _drain(build_search_strategy(config, seed=42))
        second = _drain(build_search_strategy(config, seed=42))
        assert first == second

    def test_range_specs_are_sampled_continuously(self):
        """A range spec must explore the interval, not a handful of points.

        Pre-expanding {min,max} into a list is the difference between searching
        a learning rate and testing three of them.
        """
        config = _config(
            algorithm="random",
            n_trials=20,
            search_space={"lr": {"min": 0.001, "max": 0.5}},
        )
        values = [p["lr"] for p in _drain(build_search_strategy(config, seed=7))]
        assert len(set(values)) > 10
        assert all(0.001 <= v <= 0.5 for v in values)


class TestBestSelection:
    def test_maximize_picks_the_highest(self):
        strategy = build_search_strategy(_config())
        for params, score in zip(_drain(strategy), [0.1, 0.9, 0.5, 0.3]):
            strategy.tell(params, score)
        assert strategy.best[1] == 0.9

    def test_minimize_picks_the_lowest(self):
        config = _config(objective={"metric": "rmse", "type": "minimize"})
        strategy = build_search_strategy(config)
        for params, score in zip(_drain(strategy), [10.0, 2.0, 7.0, 5.0]):
            strategy.tell(params, score)
        assert strategy.best[1] == 2.0

    def test_nan_never_wins(self):
        """Every comparison against NaN is False, so an unguarded max() would
        return whichever NaN it happened to see first."""
        strategy = build_search_strategy(_config())
        proposals = _drain(strategy)
        strategy.tell(proposals[0], float("nan"))
        strategy.tell(proposals[1], 0.4)
        strategy.tell(proposals[2], float("inf"))
        strategy.tell(proposals[3], 0.6)
        assert strategy.best[1] == 0.6

    def test_failed_trials_are_recorded_but_cannot_win(self):
        strategy = build_search_strategy(_config())
        proposals = _drain(strategy)
        for params in proposals:
            strategy.tell(params, None)
        assert strategy.best is None
        assert len(strategy.history) == 4

    def test_no_scores_at_all_has_no_best(self):
        assert build_search_strategy(_config()).best is None


class TestConfigurationErrors:
    def test_empty_search_space_is_refused(self):
        with pytest.raises(SearchError, match="search_space"):
            build_search_strategy(_config(search_space={}))

    def test_missing_objective_metric_is_refused(self):
        with pytest.raises(HyperparamConfigError, match="objective"):
            resolve_objective(_config(objective={"type": "maximize"}))

    def test_unknown_direction_is_refused(self):
        with pytest.raises(HyperparamConfigError, match="maximize"):
            resolve_objective(_config(objective={"metric": "f1", "type": "sideways"}))

    def test_resolve_objective_returns_metric_and_direction(self):
        assert resolve_objective(_config()) == ("val_f1", "maximize")

    def test_bayesian_without_optuna_says_how_to_fix_it(self):
        try:
            import optuna  # noqa: F401
        except ImportError:
            with pytest.raises(HyperparamConfigError, match="optuna"):
                _config(algorithm="bayesian")
        else:
            strategy = build_search_strategy(_config(algorithm="bayesian", n_trials=3))
            assert len(_drain(strategy)) == 3


class TestOptunaSearch:
    """Only runs where optuna is installed (it is an optional `mlops` extra)."""

    def test_learns_from_reported_scores(self):
        pytest.importorskip("optuna")
        config = _config(
            algorithm="bayesian",
            n_trials=6,
            search_space={"lr": {"min": 0.001, "max": 1.0}},
        )
        strategy = build_search_strategy(config, seed=1)

        # Objective peaks near lr=1.0; TPE should end up scoring something.
        while (params := strategy.ask()) is not None:
            strategy.tell(params, params["lr"])

        assert strategy.best is not None
        assert math.isfinite(strategy.best[1])
        assert len(strategy.history) == 6

    def test_failed_trial_is_told_to_optuna_as_a_failure(self):
        """A failed trial must not teach the sampler that the region merely
        scores badly — it has no information at all."""
        pytest.importorskip("optuna")
        config = _config(algorithm="bayesian", n_trials=2, search_space={"lr": [0.1, 0.2]})
        strategy = build_search_strategy(config, seed=1)

        first = strategy.ask()
        strategy.tell(first, None)
        second = strategy.ask()
        strategy.tell(second, 0.5)

        assert strategy.best[1] == 0.5


class TestOptunaSearchStorageAndPruning:
    """storage=/study_name= let a study resume across separate search runs;
    pruner= wires an Optuna pruner into the study. All optional, all default
    to the pre-existing in-memory/no-pruning/fresh-study behavior."""

    def test_storage_none_creates_in_memory_study(self):
        pytest.importorskip("optuna")
        config = _config(algorithm="bayesian", n_trials=2, search_space={"lr": [0.1, 0.2]})
        strategy = OptunaSearch(config, seed=1)
        # In-memory studies use Optuna's InMemoryStorage.
        assert "InMemoryStorage" in type(strategy._study._storage).__name__

    def test_storage_sqlite_persists_across_instances(self, tmp_path):
        pytest.importorskip("optuna")
        db_path = tmp_path / "study.db"
        config = _config(
            algorithm="bayesian",
            n_trials=6,
            search_space={"lr": {"min": 0.001, "max": 1.0}},
            storage=f"sqlite:///{db_path}",
            study_name="resumable-study",
        )

        first = OptunaSearch(config, seed=1, study_name=config.study_name)
        for _ in range(2):
            params = first.ask()
            first.tell(params, params["lr"])
        del first  # simulate the process ending mid-search

        second = OptunaSearch(config, seed=1, study_name=config.study_name)
        assert len(second._study.trials) == 2  # loaded, not a fresh study

        params = second.ask()
        second.tell(params, params["lr"])
        assert len(second._study.trials) == 3

    def test_without_study_name_storage_alone_does_not_resume(self, tmp_path):
        # storage= without a stable study_name can't resume: Optuna would
        # generate a random name each time, so there is nothing to find.
        pytest.importorskip("optuna")
        db_path = tmp_path / "study.db"
        config = _config(
            algorithm="bayesian",
            n_trials=2,
            search_space={"lr": [0.1, 0.2]},
            storage=f"sqlite:///{db_path}",
        )

        first = OptunaSearch(config, seed=1, study_name=None)
        params = first.ask()
        first.tell(params, params["lr"])

        second = OptunaSearch(config, seed=1, study_name=None)
        assert len(second._study.trials) == 0  # fresh study, nothing carried over

    def test_pruner_median_is_wired(self):
        pytest.importorskip("optuna")
        import optuna as optuna_module

        config = _config(
            algorithm="bayesian", n_trials=2, search_space={"lr": [0.1, 0.2]}, pruner="median"
        )
        strategy = OptunaSearch(config, seed=1)
        assert isinstance(strategy._study.pruner, optuna_module.pruners.MedianPruner)

    def test_pruner_hyperband_is_wired(self):
        pytest.importorskip("optuna")
        import optuna as optuna_module

        config = _config(
            algorithm="bayesian", n_trials=2, search_space={"lr": [0.1, 0.2]}, pruner="hyperband"
        )
        strategy = OptunaSearch(config, seed=1)
        assert isinstance(strategy._study.pruner, optuna_module.pruners.HyperbandPruner)

    def test_pruner_not_declared_leaves_optunas_own_default(self):
        # pruner=None is NOT the same as pruner="none": Optuna's own default
        # (as of Optuna 3.x) is MedianPruner, not "no pruning" — passing
        # pruner=None to create_study leaves that default in effect,
        # unchanged from before this field existed.
        pytest.importorskip("optuna")
        import optuna as optuna_module

        config = _config(algorithm="bayesian", n_trials=2, search_space={"lr": [0.1, 0.2]})
        assert config.pruner is None
        strategy = OptunaSearch(config, seed=1)
        assert isinstance(strategy._study.pruner, optuna_module.pruners.MedianPruner)

    def test_pruner_explicit_none_guarantees_no_pruning(self):
        pytest.importorskip("optuna")
        import optuna as optuna_module

        config = _config(
            algorithm="bayesian", n_trials=2, search_space={"lr": [0.1, 0.2]}, pruner="none"
        )
        assert config.pruner == "none"
        strategy = OptunaSearch(config, seed=1)
        assert isinstance(strategy._study.pruner, optuna_module.pruners.NopPruner)

    def test_unknown_pruner_raises_at_config_construction(self):
        with pytest.raises(HyperparamConfigError, match="Unknown pruner"):
            _config(algorithm="bayesian", search_space={"lr": [0.1, 0.2]}, pruner="not-a-pruner")

    def test_pruner_on_non_bayesian_algorithm_warns_but_does_not_raise(self):
        # A pruner declared for grid/random has no effect (nothing to prune),
        # but should not be a hard error — the config might be reused across
        # algorithms during experimentation.
        config = _config(algorithm="grid", pruner="median")
        assert config.pruner == "median"
