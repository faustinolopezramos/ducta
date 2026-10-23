"""`ducta.stream.plan` (what a stream would do) and `ducta.stream.node_state` (how a node is doing)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ducta.stream.node_state import derive_node_state, node_names
from ducta.stream.plan import (
    describe_node,
    describe_sink,
    describe_source,
    describe_trigger,
    plan_pipeline,
)
from ducta.stream.progress_listener import StreamingProgressSink


def _context(tmp_path, nodes, pipeline_nodes=None, **global_config):
    return SimpleNamespace(
        env="dev",
        output_path=str(tmp_path / "out"),
        global_config=global_config,
        format_policy=None,
        nodes_config=nodes,
        pipelines_config={"p": {"type": "streaming", "nodes": pipeline_nodes or list(nodes)}},
    )


def _file_node(path, out, **extra):
    return {
        "input": {"format": "file_stream", "options": {"path": str(path)}, "file_format": "json"},
        "output": {"format": "parquet", "path": str(out)},
        "streaming": {"trigger": {"type": "processing_time", "interval": "5 seconds"}},
        **extra,
    }


class TestDescriptions:
    def test_a_source_names_a_place_never_credentials(self):
        kafka = {
            "format": "kafka",
            "options": {
                "kafka.bootstrap.servers": "broker:9092",
                "subscribe": "events",
                "kafka.sasl.jaas.config": "password='hunter2'",
            },
        }
        text = describe_source(kafka)
        assert text == "kafka topic events"
        assert "hunter2" not in text and "broker" not in text

    @pytest.mark.parametrize(
        "spec,expected",
        [
            (
                {"format": "file_stream", "file_format": "json", "options": {"path": "d/in"}},
                "file_stream json d/in",
            ),
            (
                {"format": "delta_stream", "path": "t", "options": {"readChangeFeed": "true"}},
                "delta t (change feed)",
            ),
            ({"format": "delta", "path": "t"}, "delta t"),
            ({"format": "rate", "options": {"rowsPerSecond": 20}}, "rate 20 rows/s"),
            ({"format": "socket", "options": {"host": "h", "port": 9}}, "socket h:9"),
            ({"format": "kinesis", "options": {"streamName": "s"}}, "kinesis s"),
        ],
    )
    def test_sources(self, spec, expected):
        assert describe_source(spec) == expected

    def test_sinks(self):
        assert describe_sink({"format": "delta", "path": "x"}) == "delta x"
        assert describe_sink({"format": "kafka", "options": {"topic": "out"}}) == "kafka topic out"
        assert describe_sink({"format": "console"}) == "console"

    @pytest.mark.parametrize(
        "streaming,expected",
        [
            ({}, "every 10 seconds"),
            ({"trigger": {"type": "processing_time", "interval": "5 seconds"}}, "every 5 seconds"),
            ({"trigger": {"type": "available_now"}}, "available_now"),
            ({"trigger": {"type": "adaptive"}}, "adaptive"),
            ({"trigger": {"type": "continuous"}}, "continuous 1 second"),
        ],
    )
    def test_triggers(self, streaming, expected):
        assert describe_trigger(streaming) == expected


class TestNodePlan:
    def test_the_checkpoint_is_the_real_one_and_nothing_is_created(self, tmp_path):
        node = {
            **_file_node("in", "out"),
            "name": "a",
            "streaming": {"checkpoint_location": str(tmp_path / "ck")},
        }
        plan = describe_node(node, _context(tmp_path, {}), "p")
        assert plan.checkpoint == str(tmp_path / "ck" / "p" / "a")
        assert not (tmp_path / "ck").exists()

    def test_without_any_base_it_is_an_issue_not_an_exception(self, tmp_path):
        ctx = _context(tmp_path, {})
        ctx.output_path = None
        plan = describe_node({**_file_node("in", "out"), "name": "a"}, ctx, "p")
        assert plan.checkpoint is None
        assert "No checkpoint base directory" in plan.issues[0].text

    def test_the_summary_has_no_issues_or_options(self, tmp_path):
        plan = describe_node({**_file_node("in", "out"), "name": "a"}, _context(tmp_path, {}), "p")
        assert set(plan.summary()) == {"source", "sink", "trigger", "output_mode", "checkpoint"}


class TestPlanPipeline:
    def test_a_good_pipeline_has_no_problems_and_is_in_order(self, tmp_path):
        (tmp_path / "in").mkdir()
        nodes = {
            "silver": {
                **_file_node(tmp_path / "bronze", tmp_path / "silver"),
                "dependencies": ["bronze"],
            },
            "bronze": _file_node(tmp_path / "in", tmp_path / "bronze"),
        }
        plan = plan_pipeline(_context(tmp_path, nodes), "p")
        assert [n.name for n in plan.nodes] == ["bronze", "silver"]
        assert plan.errors == [] and plan.warnings == []  # silver reads what bronze writes

    def test_a_missing_source_is_a_warning_unless_another_node_writes_it(self, tmp_path):
        plan = plan_pipeline(
            _context(tmp_path, {"a": _file_node(tmp_path / "nowhere", tmp_path / "o")}), "p"
        )
        assert plan.errors == []
        assert "does not exist yet" in plan.warnings[0]

    def test_an_invalid_node_is_an_error(self, tmp_path):
        bad = _file_node(tmp_path, tmp_path / "o")
        bad["output"] = "just/a/string"
        plan = plan_pipeline(_context(tmp_path, {"a": bad}), "p")
        assert any("must be a dictionary" in e for e in plan.errors)

    def test_an_unregistered_transform_is_an_error_naming_the_import_problem(self, tmp_path):
        node = _file_node(
            tmp_path, tmp_path / "o", function={"key": "t", "module": "no_such_module_for_plan"}
        )
        plan = plan_pipeline(_context(tmp_path, {"a": node}), "p")
        (error,) = [e for e in plan.errors if "transform" in e]
        assert "'t' is not registered" in error and "could not be imported" in error

    def test_a_registered_transform_passes(self, tmp_path, monkeypatch):
        (tmp_path / "plan_transforms.py").write_text(
            "def register_transforms(registry):\n    registry.register('t', lambda df: df)\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        node = _file_node(
            tmp_path, tmp_path / "o", function={"key": "t", "module": "plan_transforms"}
        )
        assert plan_pipeline(_context(tmp_path, {"a": node}), "p").errors == []

    def test_two_nodes_may_not_share_a_checkpoint(self, tmp_path):
        # Path-hostile characters are folded into "_", so these two names collide.
        nodes = {
            "x/y": _file_node(tmp_path, tmp_path / "o1"),
            "x:y": _file_node(tmp_path, tmp_path / "o2"),
        }
        plan = plan_pipeline(_context(tmp_path, nodes), "p")
        assert any("shares its checkpoint with 'x/y'" in e for e in plan.errors)

    def test_an_undefined_node_is_an_error(self, tmp_path):
        ctx = _context(tmp_path, {}, pipeline_nodes=["ghost"])
        assert plan_pipeline(ctx, "p").errors == ["ghost: node not defined"]

    def test_an_empty_pipeline_is_an_error(self, tmp_path):
        ctx = _context(tmp_path, {})
        ctx.pipelines_config = {"p": {"type": "streaming", "nodes": []}}
        assert plan_pipeline(ctx, "p").errors == ["the pipeline has no nodes"]

    def test_it_serialises(self, tmp_path):
        d = plan_pipeline(
            _context(tmp_path, {"a": _file_node(tmp_path, tmp_path / "o")}), "p"
        ).to_dict()
        assert d["ok"] is True and d["nodes"][0]["name"] == "a"


class TestNodeState:
    SNAP = {
        "query_statuses": {
            "up": {"isActive": True},
            "dead": {"isActive": False, "exception": "boom"},
            "done": {"isActive": False},
        },
        "skipped_nodes": {"later": "upstream failed"},
        "failed_nodes": {"never": "could not start"},
        "health_monitors": {},
        "progress_metrics": {
            "up": {"batchId": 4, "numInputRows": 10, "processedRowsPerSecond": 9.5}
        },
    }

    def test_each_kind_of_node(self):
        states = {n: derive_node_state(n, self.SNAP) for n in node_names(self.SNAP)}
        assert states["up"].state == "active" and states["up"].last_batch_id == 4
        assert (states["dead"].state, states["dead"].error) == ("failed", "boom")
        assert states["done"].state == "stopped"
        assert (states["later"].state, states["later"].error) == ("skipped", "upstream failed")
        assert (states["never"].state, states["never"].error) == ("failed", "could not start")

    def test_idle_needs_a_minute_without_input(self):
        snap = {**self.SNAP, "progress_metrics": {"up": {"idleSeconds": 59.0}}}
        assert derive_node_state("up", snap).health is None
        snap["progress_metrics"]["up"]["idleSeconds"] = 61.0
        assert derive_node_state("up", snap).health == "idle"

    def test_stalled_wins_and_is_not_an_error(self):
        snap = {
            **self.SNAP,
            "health_monitors": {"up": {"error": "Query stalled: no progress for 400s"}},
            "progress_metrics": {"up": {"idleSeconds": 500.0}},
        }
        state = derive_node_state("up", snap)
        assert (state.state, state.health, state.error) == ("active", "stalled", None)


class TestIdleTracking:
    def test_idle_seconds_grow_without_input_and_reset_with_it(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr("ducta.stream.progress_listener.time.time", lambda: clock[0])
        sink = StreamingProgressSink()
        sink.record({"name": "q", "numInputRows": 5})
        assert sink.get_latest("q")["idleSeconds"] == 0.0
        clock[0] += 90
        sink.record({"name": "q", "numInputRows": 0})
        assert sink.get_latest("q")["idleSeconds"] == 90.0
        clock[0] += 10
        sink.record({"name": "q", "numInputRows": 3})
        assert sink.get_latest("q")["idleSeconds"] == 0.0

    def test_a_query_that_never_had_input_counts_from_its_first_report(self, monkeypatch):
        clock = [50.0]
        monkeypatch.setattr("ducta.stream.progress_listener.time.time", lambda: clock[0])
        sink = StreamingProgressSink()
        sink.record({"name": "q", "numInputRows": 0})
        clock[0] += 30
        sink.record({"name": "q", "numInputRows": 0})
        assert sink.get_latest("q")["idleSeconds"] == 30.0

    def test_forgetting_a_query_forgets_its_idle_clock(self):
        sink = StreamingProgressSink()
        sink.record({"name": "q", "numInputRows": 1})
        sink.forget("q")
        assert sink.get_latest("q") is None


class TestNodeOrder:
    def test_nodes_are_listed_upstream_first_when_the_snapshot_knows_the_order(self):
        snap = {"query_statuses": {"clean": {}, "ingest": {}}, "node_order": ["ingest", "clean"]}
        assert node_names(snap) == ["ingest", "clean"]

    def test_without_an_order_they_are_alphabetical(self):
        assert node_names({"query_statuses": {"clean": {}, "ingest": {}}}) == ["clean", "ingest"]

    def test_a_node_missing_from_the_order_goes_last(self):
        snap = {"query_statuses": {"a": {}, "b": {}, "c": {}}, "node_order": ["c"]}
        assert node_names(snap) == ["c", "a", "b"]


class TestRunningTotals:
    def test_rows_and_batches_with_data_are_added_up_once_per_batch(self):
        sink = StreamingProgressSink()
        sink.record({"name": "q", "batchId": 0, "numInputRows": 5})
        sink.record(
            {"name": "q", "batchId": 0, "numInputRows": 5}
        )  # the same batch, reported again
        sink.record({"name": "q", "batchId": 1, "numInputRows": 0})  # an idle report
        sink.record({"name": "q", "batchId": 2, "numInputRows": 7})
        assert sink.totals("q") == {"rows": 12.0, "batches": 2}

    def test_a_batch_that_first_reports_empty_is_counted_when_data_arrives(self):
        sink = StreamingProgressSink()
        sink.record({"name": "q", "batchId": 0, "numInputRows": 0})  # idle, same id as the next
        sink.record({"name": "q", "batchId": 0, "numInputRows": 9})
        assert sink.totals("q") == {"rows": 9.0, "batches": 1}

    def test_unknown_query_has_none_and_forgetting_clears_it(self):
        sink = StreamingProgressSink()
        assert sink.totals("nope") is None
        sink.record({"name": "q", "batchId": 0, "numInputRows": 1})
        sink.forget("q")
        assert sink.totals("q") is None
