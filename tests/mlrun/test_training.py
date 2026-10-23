"""train_with_search: the split, search, gate, tracking and registration every node repeats."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")

from sklearn.linear_model import LinearRegression, LogisticRegression  # noqa: E402
from sklearn.tree import DecisionTreeClassifier  # noqa: E402

from ducta.mlrun.hyperparams import HyperparamConfig  # noqa: E402
from ducta.mlrun.split import SplitError  # noqa: E402
from ducta.mlrun.training import TrainResult, train_with_search  # noqa: E402


@pytest.fixture(autouse=True)
def _no_stub_modules(monkeypatch):
    # tests/gate, tests/stream and tests/setting install stub `polars`/`pyspark`
    # modules when the real ones are absent; sklearn inspects whatever is in
    # sys.modules and fails on a stub (same guard as tests/mlrun/test_serving.py).
    for name in ("polars", "pyspark", "pyspark.sql"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None) is None:
            monkeypatch.delitem(sys.modules, name)


@pytest.fixture
def data():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, 2))
    y = (x[:, 0] + 0.2 * rng.normal(size=200) > 0).astype(int)
    return pd.DataFrame(x, columns=["a", "b"]), pd.Series(y, name="label")


def _context(**overrides):
    base = dict(
        split={"method": "stratified", "stratify_col": "label", "test_size": 0.25},
        node_seed=7,
        seed=42,
        cv_folds=3,
        hyperparams={},
        hyperparams_config=None,
        mlops_context=None,
        mlops_run_id=None,
        model_version=None,
    )
    return SimpleNamespace(**{**base, **overrides})


class TestSplit:
    def test_the_declared_split_is_applied_and_marked(self, data):
        X, y = data
        context = _context(split_applied=False)

        result = train_with_search(LogisticRegression(), X, y, context, task="classification")

        assert isinstance(result, TrainResult)
        assert len(result.X_train) + len(result.X_test) == 200
        assert len(result.X_test) == pytest.approx(50, abs=2)  # per-class rounding
        assert set(result.X_train.index).isdisjoint(result.X_test.index)
        assert context.split_applied is True

    def test_stratification_is_kept(self, data):
        X, y = data

        result = train_with_search(LogisticRegression(), X, y, _context(), task="classification")

        assert result.y_test.mean() == pytest.approx(y.mean(), abs=0.03)

    def test_inside_ducta_a_missing_split_is_an_error(self, data):
        X, y = data

        with pytest.raises(SplitError):
            train_with_search(
                LogisticRegression(), X, y, _context(split=None), task="classification"
            )

    def test_outside_ducta_it_falls_back_to_a_random_split(self, data):
        X, y = data

        result = train_with_search(LogisticRegression(), X, y, None, task="classification")

        assert len(result.X_test) == 40

    def test_the_target_may_not_also_be_a_feature(self, data):
        X, y = data

        with pytest.raises(ValueError, match="also in X"):
            train_with_search(
                LogisticRegression(), X.assign(label=y), y, _context(), task="classification"
            )


class TestSearch:
    def test_a_grid_from_the_pipeline_file_is_searched(self, data):
        X, y = data
        cfg = HyperparamConfig(
            algorithm="grid",
            cv_folds=3,
            objective={"metric": "roc_auc", "type": "maximize"},
            search_space={"max_depth": [1, 3]},
        )

        result = train_with_search(
            DecisionTreeClassifier(random_state=0),
            X,
            y,
            _context(hyperparams_config=cfg),
            task="classification",
        )

        assert result.best_params["max_depth"] in (1, 3)
        assert result.model.get_params()["max_depth"] == result.best_params["max_depth"]
        # the search's own score is logged under the name a sweep reads
        assert result.metrics["roc_auc"] == pytest.approx(result.cv_score)
        assert "best_cv_score" in result.metrics

    def test_an_explicit_grid_wins_over_the_context(self, data):
        X, y = data

        result = train_with_search(
            DecisionTreeClassifier(random_state=0),
            X,
            y,
            _context(),
            task="classification",
            param_grid={"max_depth": [2]},
            scoring="roc_auc",
        )

        assert result.best_params == {"max_depth": 2}

    def test_without_a_space_the_pipeline_hyperparams_are_applied_once(self, data):
        X, y = data

        result = train_with_search(
            DecisionTreeClassifier(random_state=0),
            X,
            y,
            _context(hyperparams={"max_depth": 1, "not_a_param": 9}),
            task="classification",
        )

        assert result.model.get_params()["max_depth"] == 1
        assert result.cv_score is None

    def test_a_bayesian_search_is_pointed_at_the_cli(self, data):
        X, y = data
        cfg = SimpleNamespace(
            algorithm="bayesian", search_space={"max_depth": [1, 2]}, objective={}, cv_folds=3
        )

        with pytest.raises(ValueError, match="--search"):
            train_with_search(
                DecisionTreeClassifier(),
                X,
                y,
                _context(hyperparams_config=cfg),
                task="classification",
            )

    def test_an_estimator_class_gets_the_node_seed(self, data):
        X, y = data

        result = train_with_search(
            DecisionTreeClassifier, X, y, _context(node_seed=11), task="classification"
        )

        assert result.model.get_params()["random_state"] == 11


class TestBaselineGate:
    def test_a_model_that_beats_the_baseline_passes(self, data):
        X, y = data

        result = train_with_search(
            LogisticRegression(),
            X,
            y,
            _context(),
            task="classification",
            baseline_metric="auc_roc",
            min_delta=0.1,
            extra_baselines={"baseline_auc_roc": 0.5},
        )

        assert result.metrics["auc_roc"] > 0.6
        assert "baseline_f1" in result.metrics  # merged so promotion can compare_to: baseline

    def test_a_model_that_learned_nothing_is_stopped_before_registration(self, data, tmp_path):
        X, _ = data
        noise = pd.Series(np.random.default_rng(1).integers(0, 2, len(X)), name="label")

        with pytest.raises(ValueError, match="Baseline gate FAILED"):
            train_with_search(
                LogisticRegression(),
                X,
                noise,
                _context(),
                task="classification",
                baseline_metric="auc_roc",
                min_delta=0.3,
                extra_baselines={"baseline_auc_roc": 0.5},
                name="never_saved",
            )

    def test_regression_gates_on_an_error_that_must_be_lower(self):
        rng = np.random.default_rng(2)
        X = pd.DataFrame({"a": rng.normal(size=120)})
        y = pd.Series(3 * X["a"] + rng.normal(scale=0.1, size=120), name="y")

        result = train_with_search(
            LinearRegression(),
            X,
            y,
            _context(split={"method": "random", "test_size": 0.25}),
            task="regression",
            baseline_metric="mae",
        )

        assert result.metrics["mae"] < result.metrics["baseline_mae"]
        assert {"rmse", "mae", "r2"} <= set(result.metrics)


class TestTrackingAndRegistration:
    def test_every_numeric_metric_is_logged_on_the_run(self, data):
        X, y = data
        logged = {}
        tracker = SimpleNamespace(log_metric=lambda run, key, value: logged.setdefault(key, value))
        context = _context(
            mlops_context=SimpleNamespace(experiment_tracker=tracker), mlops_run_id="run-1"
        )

        result = train_with_search(LogisticRegression(), X, y, context, task="classification")

        assert set(logged) == set(result.metrics)

    def test_the_winning_hyperparameters_are_logged_on_the_run(self, data):
        # A run table / `experiment compare` reads hyperparameters from the run, not from
        # the model it registered.
        X, y = data
        params = {}
        tracker = SimpleNamespace(
            log_metric=lambda *a: None,
            log_parameter=lambda run, key, value: params.__setitem__(key, value),
        )
        context = _context(
            mlops_context=SimpleNamespace(experiment_tracker=tracker), mlops_run_id="run-1"
        )

        result = train_with_search(
            DecisionTreeClassifier(random_state=0),
            X,
            y,
            context,
            task="classification",
            param_grid={"max_depth": [2, 3], "min_samples_leaf": [1, 4]},
        )

        assert params == result.best_params
        assert set(params) == {"max_depth", "min_samples_leaf"}

    def test_a_run_without_a_search_logs_the_hyperparameters_it_was_given(self, data):
        X, y = data
        params = {}
        tracker = SimpleNamespace(
            log_metric=lambda *a: None,
            log_parameter=lambda run, key, value: params.__setitem__(key, value),
        )
        context = _context(
            mlops_context=SimpleNamespace(experiment_tracker=tracker),
            mlops_run_id="run-1",
            hyperparams={"max_depth": 2},
        )

        train_with_search(
            DecisionTreeClassifier(random_state=0), X, y, context, task="classification"
        )

        assert params == {"max_depth": 2}

    def test_a_tracker_that_cannot_log_parameters_does_not_fail_the_node(self, data):
        X, y = data

        def boom(*args):
            raise RuntimeError("backend down")

        tracker = SimpleNamespace(log_metric=lambda *a: None, log_parameter=boom)
        context = _context(
            mlops_context=SimpleNamespace(experiment_tracker=tracker),
            mlops_run_id="run-1",
            hyperparams={"max_depth": 2},
        )

        result = train_with_search(
            DecisionTreeClassifier(random_state=0), X, y, context, task="classification"
        )

        assert result.metrics

    def test_a_tracker_that_fails_does_not_fail_the_node(self, data):
        X, y = data

        def boom(*args):
            raise RuntimeError("backend down")

        context = _context(
            mlops_context=SimpleNamespace(experiment_tracker=SimpleNamespace(log_metric=boom)),
            mlops_run_id="run-1",
        )

        result = train_with_search(LogisticRegression(), X, y, context, task="classification")

        assert result.metrics

    def test_a_named_model_is_registered_with_its_metrics_and_params(
        self, data, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        X, y = data
        seen = {}

        class _Registry:
            def register_model(self, **kwargs):
                seen.update(kwargs)
                return SimpleNamespace(version=1, artifact_uri="x://m/1")

        context = _context(
            mlops_context=SimpleNamespace(model_registry=_Registry()), mlops_run_id="run-1"
        )

        result = train_with_search(
            DecisionTreeClassifier(random_state=0),
            X,
            y,
            context,
            task="classification",
            param_grid={"max_depth": [2, 3]},
            name="tree",
        )

        assert result.persisted == {"artifact_uri": "x://m/1", "version": 1}
        assert seen["name"] == "tree" and seen["experiment_run_id"] == "run-1"
        assert seen["metrics"]["accuracy"] == result.metrics["accuracy"]
        assert seen["hyperparameters"]["max_depth"] in (2, 3)
        assert set(seen["input_schema"]) == {"a", "b"}

    def test_without_a_name_nothing_is_persisted(self, data):
        X, y = data

        result = train_with_search(LogisticRegression(), X, y, _context(), task="classification")

        assert result.persisted is None


class TestResultHelpers:
    def test_partition_frame_tags_each_row(self, data):
        X, y = data

        result = train_with_search(LogisticRegression(), X, y, _context(), task="classification")
        scored = result.partition_frame(X.assign(p=result.model.predict(X)))

        counts = scored["split"].value_counts().to_dict()
        assert set(counts) == {"train", "test"} and sum(counts.values()) == 200
        assert counts["test"] == len(result.X_test)

    def test_metrics_frame_is_one_row(self, data):
        X, y = data

        result = train_with_search(LogisticRegression(), X, y, _context(), task="classification")

        assert len(result.metrics_frame()) == 1


class TestARunThatFixesHyperparameters:
    """`--hyperparams`, a `--sweep` run and a `--search` trial give a node hyperparameters it
    must use. A search inside the node used to ignore them: every trial of `--search` trained
    the same model, and the run recorded values the model never had."""

    @staticmethod
    def _grid(**space):
        return HyperparamConfig(
            algorithm="grid",
            cv_folds=3,
            objective={"metric": "roc_auc", "type": "maximize"},
            search_space=space,
        )

    def _train(self, data, cfg, cli, **context):
        X, y = data
        return train_with_search(
            DecisionTreeClassifier(random_state=0),
            X,
            y,
            _context(hyperparams_config=cfg, cli_hyperparams=cli, hyperparams=cli, **context),
            task="classification",
        )

    def test_a_trial_that_fixes_the_whole_space_trains_exactly_that(self, data):
        cfg = self._grid(max_depth=[1, 2, 3], min_samples_leaf=[1, 5])

        for depth, leaf in [(1, 5), (3, 1)]:
            result = self._train(data, cfg, {"max_depth": depth, "min_samples_leaf": leaf})

            params = result.model.get_params()
            assert (params["max_depth"], params["min_samples_leaf"]) == (depth, leaf)
            assert result.best_params == {"max_depth": depth, "min_samples_leaf": leaf}

    def test_different_trials_give_different_models(self, data):
        cfg = self._grid(max_depth=[1, 6])

        shallow = self._train(data, cfg, {"max_depth": 1})
        deep = self._train(data, cfg, {"max_depth": 6})

        assert shallow.model.get_depth() == 1 and deep.model.get_depth() > 1
        assert shallow.best_params != deep.best_params

    def test_a_trial_still_reports_the_score_a_search_reports(self, data):
        # `--search` reads the objective's metric from the run; a one-point search is
        # still cross-validated, so it is there.
        result = self._train(data, self._grid(max_depth=[1, 6]), {"max_depth": 6})

        assert result.cv_score is not None
        assert result.metrics["roc_auc"] == pytest.approx(result.cv_score)

    def test_a_partial_override_is_fixed_and_the_rest_is_still_searched(self, data):
        cfg = self._grid(max_depth=[1, 2, 3], min_samples_leaf=[1, 20, 60])

        result = self._train(data, cfg, {"max_depth": 2})

        assert result.best_params["max_depth"] == 2
        assert result.best_params["min_samples_leaf"] in (1, 20, 60)
        assert result.model.get_params()["max_depth"] == 2

    def test_a_value_outside_the_space_is_applied_too(self, data):
        cfg = self._grid(max_depth=[1, 2])

        result = self._train(data, cfg, {"min_samples_leaf": 7})

        assert result.model.get_params()["min_samples_leaf"] == 7
        assert result.best_params["min_samples_leaf"] == 7

    def test_a_name_the_estimator_does_not_have_is_ignored(self, data):
        cfg = self._grid(max_depth=[1, 2])

        result = self._train(data, cfg, {"max_depth": 2, "sweep_extra": 1})

        assert "sweep_extra" not in result.best_params

    def test_without_overrides_the_whole_space_is_searched_as_before(self, data):
        result = self._train(data, self._grid(max_depth=[1, 3]), {})

        assert result.best_params["max_depth"] in (1, 3)

    def test_a_random_search_keeps_what_the_run_fixed(self, data):
        cfg = HyperparamConfig(
            algorithm="random",
            cv_folds=3,
            n_trials=3,
            objective={"metric": "roc_auc", "type": "maximize"},
            search_space={"max_depth": [1, 2, 3], "min_samples_leaf": [1, 5, 10]},
        )

        result = self._train(data, cfg, {"max_depth": 2})

        assert result.best_params["max_depth"] == 2
        assert result.model.get_params()["max_depth"] == 2

    def test_an_explicit_grid_is_fixed_by_the_run_too(self, data):
        X, y = data

        result = train_with_search(
            DecisionTreeClassifier(random_state=0),
            X,
            y,
            _context(cli_hyperparams={"max_depth": 3}),
            task="classification",
            param_grid={"max_depth": [1, 2], "min_samples_leaf": [1, 5]},
            scoring="roc_auc",
        )

        assert result.best_params["max_depth"] == 3

    def test_a_bayesian_trial_that_fixes_the_whole_space_runs(self, data):
        # Under `--search` the trial fixes every parameter, so the node has nothing left to
        # search. This used to raise, and every trial of a bayesian `--search` failed.
        cfg = SimpleNamespace(
            algorithm="bayesian",
            search_space={"max_depth": {"min": 1, "max": 6}, "min_samples_leaf": [1, 5]},
            objective={"metric": "roc_auc", "type": "maximize"},
            cv_folds=3,
        )

        result = self._train(data, cfg, {"max_depth": 4, "min_samples_leaf": 5})

        assert result.model.get_params()["max_depth"] == 4
        assert result.best_params == {"max_depth": 4, "min_samples_leaf": 5}

    def test_a_bayesian_run_that_leaves_parameters_free_still_goes_to_the_cli(self, data):
        cfg = SimpleNamespace(
            algorithm="bayesian",
            search_space={"max_depth": [1, 2], "min_samples_leaf": [1, 5]},
            objective={},
            cv_folds=3,
        )

        with pytest.raises(ValueError, match="--search"):
            self._train(data, cfg, {"max_depth": 2})
