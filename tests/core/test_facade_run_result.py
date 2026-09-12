"""What `PipelineExecutor.run_pipeline` actually returns, through the real facade.

`tests/core/test_results.py` covers `resolve_status` and `absorb_trace` as pure
functions, and every one of those tests passed while the facade called them in
the wrong order: `resolve_status` ran in the `else` branch, `absorb_trace` in the
`finally`, and Python runs `else` first. So the status was always decided against
an empty node list — `resolve_status`'s failed-node branch could never fire, and
its `not self.nodes` guard was trivially true.

Unit tests of the two halves could not see that. These drive the whole call.
"""

from __future__ import annotations

import pytest

from tests.core import fakes
from tests.core.fakes import (
    FakeContext,
    FakeFunctionLoader,
    FakeInputLoader,
    FakeOutputManager,
    node,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    fakes.reset()
    yield
    fakes.reset()


def _engine(nodes_config, pipelines_config, datasets=None, **settings):
    """A PipelineExecutor whose batch executor runs on in-memory collaborators."""
    from ducta.core.executors.facade import PipelineExecutor

    datasets = datasets if datasets is not None else {}
    context = FakeContext(
        nodes_config=nodes_config,
        pipelines_config=pipelines_config,
        global_config=settings,
    )
    engine = PipelineExecutor(context)

    batch = engine.batch_executor
    batch.input_loader = FakeInputLoader(datasets)
    batch.output_manager = FakeOutputManager(datasets)
    batch.node_executor.input_loader = batch.input_loader
    batch.node_executor.output_manager = batch.output_manager
    batch.node_executor._output_writer.output_manager = batch.output_manager
    batch.node_executor._function_loader = FakeFunctionLoader()
    batch.node_executor._coordinator._ml_builder = batch.node_executor._ml_builder
    return engine, context


def _one_node_pipeline(fn_name, fn):
    nodes = {"only": node(fakes.register(fn_name, fn), outputs=["out"])}
    pipelines = {"p": {"name": "p", "nodes": ["only"], "type": "batch", "requires_dates": False}}
    return nodes, pipelines


class TestTheTraceReachesTheResult:
    def test_a_clean_run_reports_its_nodes(self):
        nodes, pipelines = _one_node_pipeline("ok", fakes.passthrough("ok"))
        engine, _ = _engine(nodes, pipelines)

        result = engine.run_pipeline("p")

        assert result.ok
        assert [n.name for n in result.nodes] == ["only"]
        assert result.nodes[0].status.value == "success"

    def test_a_failing_node_raises_and_is_still_traced(self):
        # A batch node failure is raised by the coordinator, so the facade takes
        # its `except` path. The trace still has to land: it is emitted from the
        # `finally`, and it is what the run certificate is built from.
        from ducta.core.errors import PipelineExecutionError

        nodes, pipelines = _one_node_pipeline("boom", fakes.failing("boom"))
        engine, context = _engine(nodes, pipelines)

        with pytest.raises(PipelineExecutionError):
            engine.run_pipeline("p")

        from ducta.core.ledger import ledger_for

        trace = ledger_for(context).node_details
        assert [r["name"] for r in trace] == ["only"]
        assert trace[0]["status"] == "failed"
        assert "boom exploded" in trace[0]["error"]

    def test_the_certificate_records_the_resolved_status(self, tmp_path):
        # The certificate is written from `result.status`, after `resolve_status`.
        # (For a clean run both orderings agree; the case that discriminates them
        # is a run that finishes without raising but did not do its work — see
        # tests/core/test_hybrid_gate_blocked.py.)
        import json

        nodes, pipelines = _one_node_pipeline("ok", fakes.passthrough("ok"))
        engine, _ = _engine(
            nodes,
            pipelines,
            enable_run_certificate=True,
            run_certificate_dir=str(tmp_path / "runs"),
        )

        result = engine.run_pipeline("p")

        assert result.certificate_path is not None
        cert = json.loads(open(result.certificate_path, encoding="utf-8").read())
        assert cert["status"] == "success"
        assert [n["name"] for n in cert["nodes"]] == ["only"]


class TestLedgerIdentity:
    def test_the_facade_and_the_engine_share_one_ledger(self):
        # `RunLedger.start` used to construct its own instance instead of going
        # through `ledger_for`, so the facade held one ledger and every component
        # below it held another — two locks guarding the same list.
        from ducta.core.ledger import RunLedger, ledger_for

        context = FakeContext()
        started = RunLedger.start(context, "run-1")

        assert started is ledger_for(context)
        assert started.run_id == "run-1"

    def test_starting_a_run_clears_the_previous_trace(self):
        from ducta.core.ledger import RunLedger, ledger_for

        context = FakeContext()
        first = RunLedger.start(context, "run-1")
        first.record_node(name="a", status="success")
        assert len(ledger_for(context).node_details) == 1

        RunLedger.start(context, "run-2")
        assert ledger_for(context).node_details == []
