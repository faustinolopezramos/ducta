"""Running a node in its own process (`run_in_process: true`).

The DAG coordinator runs ready nodes on a ThreadPoolExecutor, which is right
for I/O and for the numpy/pandas/sklearn sections that release the GIL, and
wrong for a node whose work is pure-Python compute: those hold the GIL, so
"parallel" sibling nodes take turns instead of running at once.

Opt-in per node, and never a correctness lever — anything that would prevent
a worker from rebuilding the Context falls back to running inline.
"""

from __future__ import annotations

import pickle

from ducta.core.node_worker import (
    OUTCOME_FAILED,
    build_node_payload,
    run_node_in_process,
)


class TestPayload:
    def test_payload_is_picklable(self):
        """ProcessPoolExecutor pickles it; anything live in there would fail
        to cross the boundary."""
        payload = build_node_payload(
            "train", env="dev", ml_info={"hyperparams": {"depth": 3}, "seed": 42}
        )
        assert pickle.loads(pickle.dumps(payload)) == payload

    def test_live_handles_are_stripped_from_ml_info(self):
        """mlops_context / mlops_integration / spark are live objects the
        worker must build for itself — and that cannot be pickled."""
        payload = build_node_payload(
            "train",
            env="dev",
            ml_info={
                "hyperparams": {"depth": 3},
                "seed": 7,
                "mlops_context": object(),
                "mlops_integration": object(),
                "spark": object(),
                "hyperparams_config": object(),
            },
        )

        assert payload["ml_info"] == {"hyperparams": {"depth": 3}, "seed": 7}
        pickle.dumps(payload)  # must not raise

    def test_reproducibility_and_split_fields_survive(self):
        """A node in a worker must still receive what makes its run
        reproducible, or the same trial would train differently there."""
        payload = build_node_payload(
            "train",
            env="dev",
            ml_info={
                "seed": 42,
                "split": {"method": "stratified", "stratify_col": "target"},
                "cv_folds": 5,
                "model_version": "v3",
                "sweep_id": "s1",
                "sweep_index": 2,
            },
        )
        for key in ("seed", "split", "cv_folds", "model_version", "sweep_id", "sweep_index"):
            assert key in payload["ml_info"]


class TestWorkerNeverRaises:
    def test_a_broken_payload_comes_back_as_a_failed_outcome(self):
        """An exception crossing the pool boundary would take down nodes that
        have nothing to do with it."""
        outcome = run_node_in_process({"node_name": "train"})

        assert outcome["status"] == OUTCOME_FAILED
        assert outcome["error"]
        assert outcome["node"] == "train"

    def test_outcome_shape_is_always_complete(self):
        """The parent reads every one of these keys unconditionally."""
        outcome = run_node_in_process({"node_name": "x"})
        for key in ("node", "status", "error", "error_type"):
            assert key in outcome


class TestDispatchDecision:
    """`_should_run_in_process` decides; it must default off and degrade to
    inline rather than failing a node."""

    def _executor(self, env):
        from ducta.core.execution.runner import NodeExecutor

        executor = NodeExecutor.__new__(NodeExecutor)

        class _Settings:
            pass

        settings = _Settings()
        settings.env = env
        executor.settings = settings
        return executor

    def test_off_by_default(self):
        assert self._executor("dev")._should_run_in_process({}) is False

    def test_on_when_the_node_opts_in(self):
        assert self._executor("dev")._should_run_in_process({"run_in_process": True}) is True

    def test_falls_back_to_inline_without_a_resolvable_env(self):
        """A worker rebuilds the Context from the project config; with no env
        name there is nothing to build from. Process isolation is a
        performance choice, so it degrades instead of failing."""
        assert self._executor(None)._should_run_in_process({"run_in_process": True}) is False

    def test_is_independent_of_execution_mode(self):
        """Deliberately a separate key from `execution_mode` (already used for
        `vectorized`) so a node can be both."""
        executor = self._executor("dev")
        node = {"run_in_process": True, "execution_mode": "vectorized"}
        assert executor._should_run_in_process(node) is True
