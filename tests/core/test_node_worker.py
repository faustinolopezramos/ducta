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


class TestGateBlockedInWorker:
    """A quality gate that blocks a node in its worker process surfaces in the
    parent as QualityGateBlocked — not as a TypeError, which lost skip_retry
    and let the coordinator retry a node its gate had just blocked."""

    def _executor(self, outcome):
        from types import SimpleNamespace

        from ducta.core.execution.runner import NodeExecutor

        executor = NodeExecutor.__new__(NodeExecutor)
        executor.settings = SimpleNamespace(env="dev")
        executor.pipeline_name = "p"
        executor.context = SimpleNamespace()
        executor._run_child = lambda node_name, payload: outcome
        return executor

    def test_the_parent_raises_the_same_exception(self):
        import pytest

        from ducta.check.core import QualityGateBlocked

        outcome = {
            "status": "gate_blocked",
            "error": "blocked",
            "gate": {
                "dataset_name": "silver.orders",
                "run_id": "r1",
                "gate_name": "freshness",
                "triggered_rules": ["rows < 10"],
            },
        }
        with pytest.raises(QualityGateBlocked) as caught:
            self._executor(outcome)._run_node_in_subprocess("clean", {}, "", "", {})

        error = caught.value
        assert error.dataset_name == "silver.orders" and error.run_id == "r1"
        assert error.skip_retry is True
        assert "freshness" in str(error) and "rows < 10" in str(error)

    def test_an_outcome_without_gate_detail_still_raises_it(self):
        import pytest

        from ducta.check.core import QualityGateBlocked

        with pytest.raises(QualityGateBlocked, match="worker said no"):
            self._executor(
                {"status": "gate_blocked", "error": "worker said no"}
            )._run_node_in_subprocess("clean", {}, "", "", {})


class TestWorkerSeesWhatTheParentRunChanged:
    """A sample run redirects a Context after loading it; the worker rebuilds its own."""

    PROJECT = {
        "ducta.yaml": "version: 2\nproject: demo\npaths: {input: data, output: out}\n",
        "catalog.yaml": (
            "raw:\n  format: csv\n  path: ${paths.input}/raw.csv\n"
            "gold.sales.totals:\n  format: parquet\n  path: ${paths.output}/${env}/gold/totals\n"
        ),
        "pipelines/etl.yaml": (
            "nodes:\n  totals:\n    run: pipelines.etl:totals\n    inputs: [raw]\n"
            "    outputs: [gold.sales.totals]\n    run_in_process: true\n"
        ),
    }

    def _project(self, tmp_path):
        for name, text in self.PROJECT.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return tmp_path

    def test_a_sample_run_worker_writes_to_the_scratch_and_reads_the_sample(
        self, tmp_path, monkeypatch
    ):
        from ducta.core.node_worker import build_node_payload
        from ducta.core.worker_bootstrap import bootstrap_worker_context, capture_run_overrides
        from ducta.setting.project.context import load_project_context
        from ducta_server.execution.runner import redirect_to_scratch

        root = self._project(tmp_path)
        monkeypatch.chdir(root)
        _, parent = load_project_context(root, "dev")
        scratch = redirect_to_scratch(parent, "dev", 25)

        payload = build_node_payload(
            "totals",
            env="dev",
            ml_info={},
            base_path=str(root),
            output_path=str(parent.output_path),
            overrides=capture_run_overrides(parent),
        )
        payload = pickle.loads(pickle.dumps(payload))  # it crosses a process boundary
        _, worker = bootstrap_worker_context(payload)

        written = worker.output_config["gold.sales.totals"]["filepath"]
        assert written == parent.output_config["gold.sales.totals"]["filepath"]
        assert str(scratch) in written
        assert worker.sample_rows == 25
        assert worker.global_config["run_certificate_dir"] == str(scratch / ".ducta" / "runs")
        assert worker.global_config["chain"]["state_dir"].startswith(str(scratch))

    def test_without_overrides_the_worker_is_what_the_project_says(self, tmp_path, monkeypatch):
        from ducta.core.node_worker import build_node_payload
        from ducta.core.worker_bootstrap import bootstrap_worker_context

        root = self._project(tmp_path)
        monkeypatch.chdir(root)
        payload = build_node_payload("totals", env="dev", ml_info={}, base_path=str(root))
        _, worker = bootstrap_worker_context(payload)
        assert worker.output_config["gold.sales.totals"]["filepath"] == "out/dev/gold/totals"
        assert getattr(worker, "sample_rows", None) is None

    def test_the_api_trust_boundary_travels_to_the_worker(self, tmp_path, monkeypatch):
        from ducta.core.node_worker import build_node_payload
        from ducta.core.worker_bootstrap import bootstrap_worker_context, capture_run_overrides
        from ducta.setting.project.loader import load_project_v2

        root = self._project(tmp_path)
        monkeypatch.chdir(root)
        parent = load_project_v2(root, "dev", allow_python_config=False)
        overrides = capture_run_overrides(parent)
        assert overrides["allow_python_config"] is False

        payload = build_node_payload(
            "totals", env="dev", ml_info={}, base_path=str(root), overrides=overrides
        )
        _, worker = bootstrap_worker_context(payload)
        assert worker.allow_python_config is False


class TestAReproductionWorkerKeepsItsIsolation:
    """A run_in_process node rebuilt its Context from the project files: a reproduction's
    scratch registry and its pinned models did not reach it, and with ``mlops_path``
    in ducta.yaml its training node registered and promoted in the real registry."""

    PROJECT = {
        **TestWorkerSeesWhatTheParentRunChanged.PROJECT,
        "ducta.yaml": (
            "version: 2\nproject: demo\npaths: {input: data, output: out}\n"
            "settings: {mlops_path: models}\n"
        ),
    }

    def test_the_worker_registers_in_the_scratch_and_serves_the_pinned_version(
        self, tmp_path, monkeypatch
    ):
        from ducta.core.node_worker import build_node_payload
        from ducta.core.scratch import pin_served_models, prepare_reproduction
        from ducta.core.worker_bootstrap import bootstrap_worker_context, capture_run_overrides
        from ducta.setting.project.context import load_project_context

        for name, text in self.PROJECT.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        monkeypatch.chdir(tmp_path)
        _, parent = load_project_context(tmp_path, "dev")
        real = parent.global_config["mlops_path"]
        target = prepare_reproduction(parent, "dev", "r1", "etl")
        pin_served_models(parent, {"nodes": [{"ml": {"model": {"name": "m", "version": 1}}}]})

        payload = build_node_payload(
            "totals",
            env="dev",
            ml_info={},
            base_path=str(tmp_path),
            output_path=str(parent.output_path),
            overrides=capture_run_overrides(parent),
        )
        _, worker = bootstrap_worker_context(pickle.loads(pickle.dumps(payload)))

        assert worker.global_config["mlops_path"] == str(target / ".ducta" / "mlops")
        assert worker.serving_mlops_path == parent.serving_mlops_path
        assert real in worker.serving_mlops_path
        assert worker.pinned_models == {"m": 1}


class TestTheWorkersMlEvidenceReachesTheParent:
    """The certificate of a run_in_process ML node had no ``ml`` record: no split, no
    served model, no registered version."""

    def test_it_is_handed_back(self):
        from types import SimpleNamespace

        from ducta.core.execution.runner import NodeExecutor

        executor = NodeExecutor.__new__(NodeExecutor)
        executor.settings = SimpleNamespace(env="dev")
        executor.pipeline_name = "p"
        executor.context = SimpleNamespace()
        ml = {"stage": "training", "registered": [{"name": "m", "version": 2}]}
        executor._run_child = lambda node_name, payload: {
            "status": "success",
            "node_trace": [{"name": "fit", "status": "success", "ml": ml}],
        }
        evidence: dict = {}
        executor._run_node_in_subprocess("fit", {}, "", "", {}, evidence)
        assert evidence == {"ml": ml}


def test_the_worker_runs_the_node_itself():
    """The worker read ``run_in_process: true`` too and started a worker of its own,
    which a daemonic process may not: every run_in_process node failed."""
    from types import SimpleNamespace

    from ducta.core.execution.runner import NodeExecutor

    executor = NodeExecutor.__new__(NodeExecutor)
    executor.settings = SimpleNamespace(env="dev")
    assert executor._should_run_in_process({"run_in_process": True}) is True
    executor.in_worker = True
    assert executor._should_run_in_process({"run_in_process": True}) is False


class TestTheWorkersEvidenceReachesTheCertificate:
    """The worker read, wrote, hashed and checked in its own process: the parent's
    certificate had none of it ("records no outputs — nothing to reproduce")."""

    def test_the_parent_ledger_adopts_it(self):
        from types import SimpleNamespace

        from ducta.core.ledger import RunLedger

        child = RunLedger.start(SimpleNamespace(), "child")
        child._write("_output_fingerprints", {"gold.a": {"value": "h1"}})
        child._write("_input_fingerprints", {"raw": {"value": "h0"}})
        child.record_code("fit", {"sha256": "c"})
        child.record_quality({"node": "fit", "failed_checks": ["prediction_drift"]})
        evidence = pickle.loads(pickle.dumps(child.worker_evidence()))

        parent = RunLedger.start(SimpleNamespace(), "parent")
        parent.adopt_worker_evidence(evidence)
        assert parent.output_fingerprints == {"gold.a": {"value": "h1"}}
        assert parent.input_fingerprints == {"raw": {"value": "h0"}}
        assert parent.code_fingerprints == {"fit": {"sha256": "c"}}
        assert parent.quality_results[0]["failed_checks"] == ["prediction_drift"]
        assert parent.evidence_complete

    def test_a_gap_in_the_worker_is_a_gap_in_the_run(self):
        from types import SimpleNamespace

        from ducta.core.ledger import RunLedger

        parent = RunLedger.start(SimpleNamespace(), "parent")
        parent.adopt_worker_evidence({"gaps": ["output skipped"]})
        assert not parent.evidence_complete


class TestATrackedRunsWorkerRegistersItsModel:
    """The worker had no MLOps context: persist_model found no registry, wrote a local
    pickle and never registered or promoted the model."""

    def test_the_tracked_run_id_travels(self):
        from ducta.core.node_worker import build_node_payload

        payload = build_node_payload("fit", env="dev", ml_info={"mlops_run_id": "r1", "x": 1})
        assert payload["ml_info"] == {"mlops_run_id": "r1"}

    def test_a_worker_that_cannot_open_the_registry_fails(self, monkeypatch):
        import pytest

        from ducta.core import node_worker
        from ducta.mlrun import config

        monkeypatch.setattr(
            config.MLOpsContext,
            "from_context",
            classmethod(lambda cls, context, pipeline_name=None: None),
        )
        with pytest.raises(RuntimeError, match="could not open its model registry"):
            node_worker._worker_mlops_context(object(), "train")
