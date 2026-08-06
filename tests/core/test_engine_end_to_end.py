"""End-to-end coverage of the DAG engine, without Spark.

`tests/integration` skips entirely when pyspark is absent, so the coordination
loop — submission, completion handling, skip cascades, timeout handling, the
accounting that guarantees no node is silently dropped — had no end-to-end test
at all. Every collaborator it uses is injected, so it runs in-process on lists.
"""

from __future__ import annotations

import threading

import pytest

from tests.core import fakes
from tests.core.fakes import (
    FakeContext,
    FakeFrame,
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


def _executor(nodes_config, datasets=None, monkeypatch=None, **settings):
    """A NodeExecutor wired to in-memory collaborators."""
    from ducta.core.execution.runner import NodeExecutor

    datasets = datasets if datasets is not None else {}
    context = FakeContext(nodes_config=nodes_config, global_settings=settings)
    loader = FakeInputLoader(datasets)
    output = FakeOutputManager(datasets)

    executor = NodeExecutor(context, loader, output, max_workers=settings.get("max_workers", 4))
    # Resolve node functions from the test registry rather than the filesystem.
    executor._function_loader = FakeFunctionLoader()
    executor._coordinator._ml_builder = executor._ml_builder
    return executor, context, output


def _run(executor, nodes_config, order=None):
    from ducta.core.dependency_resolver import DependencyResolver

    names = order or list(nodes_config)
    dag = DependencyResolver.build_dependency_graph(names, nodes_config)
    execution_order = DependencyResolver.topological_sort(dag)
    executor.execute_nodes_parallel(
        execution_order, nodes_config, dag, "2024-01-01", "2024-01-02", {}
    )


class TestLinearPipeline:
    def test_a_chain_runs_in_dependency_order(self):
        cfg = {
            "extract": node(
                fakes.register("extract", fakes.passthrough("extract")), outputs=["raw"]
            ),
            "clean": node(
                fakes.register("clean", fakes.passthrough("clean")),
                inputs=["raw"],
                outputs=["clean"],
            ),
            "report": node(fakes.register("report", fakes.passthrough("report")), inputs=["clean"]),
        }
        executor, _, output = _executor(cfg)

        _run(executor, cfg)

        assert fakes.EXECUTED == ["extract", "clean", "report"]
        assert output.saved == ["raw", "clean"]

    def test_data_flows_from_producer_to_consumer(self):
        frame = FakeFrame([{"id": 7, "value": "x"}], name="produced")

        def produce(*_, start_date=None, end_date=None, **kw):
            return frame

        seen = {}

        def consume(*frames, start_date=None, end_date=None, **kw):
            seen["input"] = frames[0]
            return frames[0]

        cfg = {
            "a": node(fakes.register("produce", produce), outputs=["ds"]),
            "b": node(fakes.register("consume", consume), inputs=["ds"]),
        }
        executor, _, _ = _executor(cfg)

        _run(executor, cfg)

        assert seen["input"] is frame


class TestParallelism:
    def test_independent_nodes_really_run_concurrently(self):
        # A barrier only clears if both nodes are inside their function at once.
        barrier = threading.Barrier(2)
        cfg = {
            "a": node(fakes.register("a", fakes.concurrent_probe("a", barrier))),
            "b": node(fakes.register("b", fakes.concurrent_probe("b", barrier))),
        }
        executor, _, _ = _executor(cfg, max_workers=2)

        _run(executor, cfg)  # would deadlock (and time out) if run sequentially

        assert sorted(fakes.EXECUTED) == ["a", "b"]

    def test_a_diamond_runs_each_node_exactly_once(self):
        cfg = {
            "root": node(fakes.register("root", fakes.passthrough("root")), outputs=["r"]),
            "left": node(
                fakes.register("left", fakes.passthrough("left")), inputs=["r"], outputs=["l"]
            ),
            "right": node(
                fakes.register("right", fakes.passthrough("right")), inputs=["r"], outputs=["rt"]
            ),
            "join": node(fakes.register("join", fakes.passthrough("join")), inputs=["l", "rt"]),
        }
        executor, _, _ = _executor(cfg)

        _run(executor, cfg)

        assert sorted(fakes.EXECUTED) == ["join", "left", "right", "root"]
        assert fakes.EXECUTED[0] == "root"
        assert fakes.EXECUTED[-1] == "join"


class TestFailurePropagation:
    def test_a_failing_node_fails_the_pipeline_with_its_root_cause(self):
        cfg = {
            "ok": node(fakes.register("ok", fakes.passthrough("ok"))),
            "bad": node(
                fakes.register("bad", fakes.failing("bad", ValueError("column 'x' not found")))
            ),
        }
        executor, _, _ = _executor(cfg)

        with pytest.raises(RuntimeError) as caught:
            _run(executor, cfg)

        # The real error, not a generic "failed due to node failures".
        assert "bad" in str(caught.value)
        assert "column 'x' not found" in str(caught.value)
        assert isinstance(caught.value.__cause__, ValueError)

    def test_a_downstream_node_does_not_run_after_its_dependency_fails(self):
        cfg = {
            "a": node(fakes.register("a", fakes.failing("a")), outputs=["ds"]),
            "b": node(fakes.register("b", fakes.passthrough("b")), inputs=["ds"]),
        }
        executor, _, _ = _executor(cfg)

        with pytest.raises(RuntimeError):
            _run(executor, cfg)

        assert "b" not in fakes.EXECUTED


class TestAccounting:
    def test_every_node_is_accounted_for(self):
        # A node whose dependency lives outside the pipeline would never become
        # ready; the run must report that rather than exit quietly.
        cfg = {
            "a": node(fakes.register("a", fakes.passthrough("a"))),
            "orphan": node(
                fakes.register("orphan", fakes.passthrough("orphan")),
                dependencies=["not_in_pipeline"],
            ),
        }
        executor, _, _ = _executor(cfg)

        from ducta.core.dependency_resolver import DependencyResolver

        dag = {"a": set(), "orphan": set()}
        order = DependencyResolver.topological_sort(dag)

        with pytest.raises(RuntimeError, match="never executed|not executed"):
            executor.execute_nodes_parallel(order, cfg, dag, "2024-01-01", "2024-01-02", {})

    def test_the_run_trace_records_every_node(self):
        cfg = {
            "a": node(fakes.register("a", fakes.passthrough("a")), outputs=["x"]),
            "b": node(fakes.register("b", fakes.passthrough("b")), inputs=["x"]),
        }
        executor, context, _ = _executor(cfg)

        _run(executor, cfg)

        from ducta.core.ledger import ledger_for

        recorded = {r["name"]: r for r in ledger_for(context).node_details}
        assert set(recorded) == {"a", "b"}
        assert all(r["status"] == "success" for r in recorded.values())
        assert recorded["a"]["outputs"] == ["x"]


class TestMissingDependencySkips:
    def test_a_node_with_absent_inputs_is_skipped_along_with_its_descendants(self):
        cfg = {
            "a": node(
                fakes.register("a", fakes.passthrough("a")),
                inputs=["never_produced"],
                outputs=["x"],
                skip_missing_deps=True,
            ),
            "b": node(fakes.register("b", fakes.passthrough("b")), inputs=["x"]),
        }
        executor, context, _ = _executor(cfg)

        _run(executor, cfg)  # a skip is not a failure

        assert fakes.EXECUTED == []
        from ducta.core.ledger import ledger_for

        statuses = {r["name"]: r["status"] for r in ledger_for(context).node_details}
        assert statuses == {"a": "skipped", "b": "skipped"}


class TestTimeouts:
    def test_a_node_over_its_budget_aborts_the_run(self):
        cfg = {"slow": node(fakes.register("slow", fakes.slow("slow", 2.0)))}
        executor, _, _ = _executor(cfg)
        executor._coordinator.node_timeout = 0.2

        with pytest.raises(RuntimeError, match="timeout"):
            _run(executor, cfg)

    def test_a_fast_node_is_unaffected_by_the_budget(self):
        cfg = {"quick": node(fakes.register("quick", fakes.passthrough("quick")))}
        executor, _, _ = _executor(cfg)
        executor._coordinator.node_timeout = 30

        _run(executor, cfg)

        assert fakes.EXECUTED == ["quick"]


class TestRetry:
    def test_a_node_marked_retry_is_retried_and_can_succeed(self):
        attempts = {"n": 0}

        def flaky(*_, start_date=None, end_date=None, **kw):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("transient")
            return FakeFrame(name="flaky")

        cfg = {"flaky": node(fakes.register("flaky", flaky), retry=3)}
        executor, _, _ = _executor(cfg)

        _run(executor, cfg)

        assert attempts["n"] == 3

    def test_retries_are_exhausted_and_the_failure_surfaces(self):
        cfg = {"always": node(fakes.register("always", fakes.failing("always")), retry=2)}
        executor, _, _ = _executor(cfg)

        with pytest.raises(RuntimeError, match="always"):
            _run(executor, cfg)
