"""`execute_sweep` must forward what makes a sweep a sweep.

The expansion was always right — `expand_sweep` produced the correct grid — but
the per-combination hyperparameters were assembled into a local `merged` dict
and then never passed to `execute()`. Every run in the sweep therefore executed
the pipeline with the *same* (empty) hyperparameters while still reporting
distinct `sweep_index` values, so the response looked correct from the outside
and the results were quietly meaningless.

`user_id` was dropped the same way, which is an access-control bug rather than a
numerical one: `_get_owned` and `list_executions` filter on it, so with
`AUTH_ENABLED=true` the user who launched a sweep could not list, tail or cancel
their own runs.

The assertions below are written against the *observable* contract of
`execute_sweep` — what it passes to `execute` — because nothing downstream of it
can tell a correctly-parameterised sweep from a broken one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from ducta.api.execution.manager import ExecutionManager
from ducta.api.models.execution import ExecutionResponse, ExecutionStatus


@pytest.fixture
def calls() -> List[Dict[str, Any]]:
    return []


@pytest.fixture
def manager(calls: List[Dict[str, Any]]) -> ExecutionManager:
    """An ExecutionManager whose `execute` is a spy.

    Built with `object.__new__` deliberately: `execute_sweep` touches no
    instance state other than `self.execute`, so constructing the real thing
    would spin up a store, a queue, a log buffer and a runs directory purely to
    throw them away — and would couple this test to all of that.
    """
    mgr = object.__new__(ExecutionManager)

    def _spy(**kwargs: Any) -> ExecutionResponse:
        calls.append(kwargs)
        return ExecutionResponse(
            id=f"exec-{len(calls)}",
            pipeline_name=kwargs["pipeline_name"],
            env=kwargs["env"],
            status=ExecutionStatus.PENDING,
            user_id=kwargs.get("user_id"),
            sweep_id=kwargs.get("sweep_id"),
            sweep_index=kwargs.get("sweep_index"),
        )

    mgr.execute = _spy  # type: ignore[method-assign]
    return mgr


def _sweep(manager: ExecutionManager, **overrides: Any):
    kwargs: Dict[str, Any] = {
        "source_path": Path("/tmp/does-not-need-to-exist"),
        "pipeline_name": "train",
        "env": "dev",
        "sweep": {"lr": [0.1, 0.2], "depth": [3, 5]},
        "base_hyperparams": {"epochs": 10},
        "model_version": "v3",
        "project_id": "proj",
        "user_id": "user-42",
    }
    kwargs.update(overrides)
    return manager.execute_sweep(**kwargs)


class TestHyperparameterForwarding:
    def test_each_combination_gets_its_own_hyperparameters(self, manager, calls):
        # The regression: all four used to arrive as None, so the sweep ran the
        # same configuration four times.
        _sweep(manager)

        grids = [{k: v for k, v in c["hyperparams"].items() if k in ("lr", "depth")} for c in calls]
        assert grids == [
            {"lr": 0.1, "depth": 3},
            {"lr": 0.1, "depth": 5},
            {"lr": 0.2, "depth": 3},
            {"lr": 0.2, "depth": 5},
        ]

    def test_base_hyperparams_are_merged_into_every_run(self, manager, calls):
        _sweep(manager)
        assert all(c["hyperparams"]["epochs"] == 10 for c in calls)

    def test_the_grid_overrides_a_colliding_base_value(self, manager, calls):
        # A base value and a swept value for the same key: the swept one wins,
        # otherwise the sweep could not vary that parameter at all.
        _sweep(manager, base_hyperparams={"lr": 99.0, "epochs": 10})
        assert sorted(c["hyperparams"]["lr"] for c in calls) == [0.1, 0.1, 0.2, 0.2]

    def test_sweep_metadata_travels_inside_the_hyperparameters(self, manager, calls):
        response = _sweep(manager)
        for index, call in enumerate(calls, start=1):
            assert call["hyperparams"]["sweep_id"] == response.sweep_id
            assert call["hyperparams"]["sweep_index"] == index

    def test_hyperparameter_dicts_are_not_shared_between_runs(self, manager, calls):
        # A single dict mutated in the loop would make every run see the last
        # combination once the executions are actually consumed.
        _sweep(manager)
        assert len({id(c["hyperparams"]) for c in calls}) == len(calls)


class TestOwnershipAndMetadata:
    def test_user_id_reaches_every_run(self, manager, calls):
        # Without this the launching user cannot see their own sweep:
        # `_get_owned` and `list_executions` filter on `user_id`.
        _sweep(manager)
        assert [c["user_id"] for c in calls] == ["user-42"] * 4

    def test_model_version_reaches_every_run(self, manager, calls):
        _sweep(manager)
        assert [c["model_version"] for c in calls] == ["v3"] * 4

    def test_the_returned_records_carry_the_owner(self, manager):
        response = _sweep(manager)
        assert all(e.user_id == "user-42" for e in response.executions)


class TestSweepGrouping:
    def test_all_runs_share_one_sweep_id_with_sequential_indices(self, manager, calls):
        response = _sweep(manager)
        assert {c["sweep_id"] for c in calls} == {response.sweep_id}
        assert [c["sweep_index"] for c in calls] == [1, 2, 3, 4]

    def test_response_totals_match_the_expansion(self, manager):
        response = _sweep(manager)
        assert response.total == 4
        assert len(response.executions) == 4

    def test_a_grid_over_the_limit_raises_value_error_and_queues_nothing(self, manager, calls):
        # 100 combinations against the default max_sweep_size of 50.
        # routes/projects.py turns ValueError into a 422; a SweepError leaking
        # through would surface as a 500 instead. Nothing may be queued either:
        # the limit exists to stop a large grid from flooding the queue.
        with pytest.raises(ValueError):
            _sweep(manager, sweep={"a": list(range(10)), "b": list(range(10))})
        assert calls == [], "nothing should be queued when the spec is rejected"
