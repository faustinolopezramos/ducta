"""Unit tests for ducta.core.sweep_worker — running a trial in its own process.

Trials cannot be parallelized in-process: RunLedger is a view over attributes
stashed on the shared Context and RunLedger.start() clears the previous run's
evidence, so concurrent runs would interleave into each other's certificates;
and node outputs are addressed under context.output_path, so concurrent trials
would clobber each other's datasets. These pin the isolation that makes
parallel trials safe.
"""

from __future__ import annotations

import pickle
from pathlib import Path

from ducta.core.sweep_worker import (
    build_payloads,
    run_trial_in_process,
    shared_prefix_path,
    trial_output_path,
)


class TestTrialOutputIsolation:
    def test_each_trial_gets_its_own_directory(self):
        paths = {trial_output_path("/data/out", "search-1", i) for i in range(1, 5)}
        assert len(paths) == 4

    def test_path_is_scoped_by_search_id(self):
        """Two searches must not share trial directories, or a later search
        would read a previous one's materialized outputs."""
        first = trial_output_path("/data/out", "search-1", 1)
        second = trial_output_path("/data/out", "search-2", 1)
        assert first != second

    def test_path_stays_under_the_project_output_path(self):
        path = Path(trial_output_path("/data/out", "search-1", 3))
        assert str(path).startswith("/data/out")
        assert path.name == "trial_3"


class TestSharedPrefixPath:
    def test_scoped_by_search_id(self):
        first = shared_prefix_path("/data/out", "search-1")
        second = shared_prefix_path("/data/out", "search-2")
        assert first != second

    def test_distinct_from_any_trial_output_path(self):
        shared = shared_prefix_path("/data/out", "search-1")
        assert shared not in {trial_output_path("/data/out", "search-1", i) for i in range(1, 10)}

    def test_stays_under_the_project_output_path(self):
        path = Path(shared_prefix_path("/data/out", "search-1"))
        assert str(path).startswith("/data/out")


class TestPayloads:
    def _trials(self, n=2):
        return [
            {"index": i, "params": {"depth": i}, "hyperparams": {"depth": i, "sweep_id": "s"}}
            for i in range(1, n + 1)
        ]

    def test_payloads_are_picklable(self):
        """ProcessPoolExecutor pickles the payload; a Context or executor in
        there would fail to cross the boundary (or silently carry a Spark
        session into the child)."""
        payloads = build_payloads(
            self._trials(),
            env="dev",
            pipeline="train",
            search_id="s1",
            base_output_path="/data/out",
        )
        assert pickle.loads(pickle.dumps(payloads)) == payloads

    def test_payload_carries_an_isolated_output_path(self):
        payloads = build_payloads(
            self._trials(),
            env="dev",
            pipeline="train",
            search_id="s1",
            base_output_path="/data/out",
        )
        assert payloads[0]["output_path"] == "/data/out/_trials/s1/trial_1"
        assert payloads[1]["output_path"] == "/data/out/_trials/s1/trial_2"

    def test_no_output_path_means_no_isolation_directory(self):
        """The driver checks for this and refuses to run in parallel rather
        than letting trials share one directory."""
        payloads = build_payloads(
            self._trials(1), env="dev", pipeline="train", search_id="s1", base_output_path=None
        )
        assert payloads[0]["output_path"] is None

    def test_params_and_hyperparams_stay_separate(self):
        """`hyperparams` goes to the pipeline (with sweep tags); `params` is
        what gets reported back to the search strategy, and the tags would
        corrupt the strategy's key for the trial."""
        payloads = build_payloads(
            self._trials(1), env="dev", pipeline="train", search_id="s1", base_output_path="/o"
        )
        assert payloads[0]["params"] == {"depth": 1}
        assert "sweep_id" in payloads[0]["hyperparams"]
        assert "sweep_id" not in payloads[0]["params"]

    def test_read_fallback_paths_defaults_to_empty_list(self):
        """A caller that doesn't pass read_fallback_paths (any existing
        caller predating this field) gets the exact previous behavior: no
        fallback, no shared-prefix reuse."""
        payloads = build_payloads(
            self._trials(1), env="dev", pipeline="train", search_id="s1", base_output_path="/o"
        )
        assert payloads[0]["read_fallback_paths"] == []

    def test_read_fallback_paths_passed_through_to_every_trial(self):
        payloads = build_payloads(
            self._trials(3),
            env="dev",
            pipeline="train",
            search_id="s1",
            base_output_path="/o",
            read_fallback_paths=["/o/_trials/s1/_shared"],
        )
        assert all(p["read_fallback_paths"] == ["/o/_trials/s1/_shared"] for p in payloads)

    def test_read_fallback_paths_are_still_picklable(self):
        payloads = build_payloads(
            self._trials(1),
            env="dev",
            pipeline="train",
            search_id="s1",
            base_output_path="/o",
            read_fallback_paths=["/o/_trials/s1/_shared"],
        )
        assert pickle.loads(pickle.dumps(payloads)) == payloads


class TestWorkerNeverRaises:
    def test_a_broken_payload_comes_back_as_a_failed_trial(self):
        """A worker must always answer: an exception crossing the pool
        boundary would take down trials that have nothing to do with it."""
        result = run_trial_in_process({"trial_index": 1, "params": {"a": 1}})

        assert result["failed"] is True
        assert result["reason"]
        assert result["index"] == 1
        assert result["params"] == {"a": 1}

    def test_missing_project_reports_a_useful_reason(self, tmp_path):
        result = run_trial_in_process(
            {
                "trial_index": 2,
                "params": {},
                "hyperparams": {},
                "env": "dev",
                "pipeline": "train",
                "base_path": str(tmp_path),
                "output_path": str(tmp_path / "out"),
                "quiet": True,
            }
        )

        assert result["failed"] is True
        assert "ConfigurationError" in result["reason"] or "Error" in result["reason"]

    def test_result_shape_is_always_complete(self):
        """The driver reads every one of these keys unconditionally."""
        result = run_trial_in_process({"trial_index": 9})
        for key in ("index", "params", "metrics", "gate_blocked", "failed", "reason"):
            assert key in result
