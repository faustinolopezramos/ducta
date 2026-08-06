"""PipelineRunResult: one typed outcome instead of Union[None, str, Dict].

The union return type is what let a failed hybrid pipeline be returned like any
other value (so the chain runner never saw it) and forced callers to reach
through `exec_obj._batch_executor.node_executor.gate_blocked` for outcomes that
do not raise.
"""

from __future__ import annotations

from ducta.core.results import NodeOutcome, NodeStatus, PipelineRunResult, RunStatus


class TestOkSemantics:
    def test_a_clean_run_is_ok(self):
        assert PipelineRunResult(pipeline="p").ok is True

    def test_bool_matches_ok(self):
        assert bool(PipelineRunResult(pipeline="p")) is True
        assert bool(PipelineRunResult(pipeline="p", status=RunStatus.FAILED)) is False

    def test_a_gate_block_is_not_ok(self):
        # The run finished without raising, but nodes were skipped. Treating
        # that as success is the exact defect this type exists to prevent.
        result = PipelineRunResult(pipeline="p", status=RunStatus.GATE_BLOCKED)
        assert result.ok is False
        assert result.failed is False

    def test_a_still_running_stream_is_not_ok(self):
        assert PipelineRunResult(pipeline="p", status=RunStatus.RUNNING).ok is False

    def test_a_skipped_run_is_not_ok_but_is_not_failed(self):
        result = PipelineRunResult(pipeline="p", status=RunStatus.SKIPPED)
        assert result.ok is False
        assert result.failed is False


class TestAddError:
    def test_recording_an_error_marks_the_run_failed(self):
        result = PipelineRunResult(pipeline="p")
        result.add_error("boom")

        assert result.failed
        assert result.errors == ["boom"]
        assert not result.ok


class TestResolveStatus:
    def test_a_recorded_error_wins(self):
        result = PipelineRunResult(pipeline="p", errors=["boom"], gate_blocked={"n": {}})
        assert result.resolve_status().status is RunStatus.FAILED

    def test_a_failed_node_marks_the_run_failed(self):
        result = PipelineRunResult(
            pipeline="p",
            nodes=[NodeOutcome(name="n", status=NodeStatus.FAILED, error="boom")],
        )
        assert result.resolve_status().status is RunStatus.FAILED

    def test_a_gate_block_outranks_a_skip(self):
        # A gate block means data was rejected; a skip means data was absent.
        result = PipelineRunResult(pipeline="p", gate_blocked={"n": {}}, skipped={"m": "no inputs"})
        assert result.resolve_status().status is RunStatus.GATE_BLOCKED

    def test_a_skip_with_no_nodes_run_is_a_skipped_run(self):
        result = PipelineRunResult(pipeline="p", skipped={"n": "no inputs"})
        assert result.resolve_status().status is RunStatus.SKIPPED

    def test_a_clean_run_stays_success(self):
        result = PipelineRunResult(pipeline="p", nodes=[NodeOutcome(name="n")])
        assert result.resolve_status().status is RunStatus.SUCCESS


class TestAbsorbTrace:
    def test_trace_records_become_node_outcomes(self):
        result = PipelineRunResult(pipeline="p").absorb_trace(
            [
                {
                    "name": "extract",
                    "type": "batch",
                    "status": "success",
                    "duration_seconds": 1.25,
                    "outputs": ["bronze.raw.sales"],
                    "error": None,
                }
            ]
        )

        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.name == "extract"
        assert node.status is NodeStatus.SUCCESS
        assert node.duration_seconds == 1.25
        assert node.outputs == ["bronze.raw.sales"]

    def test_nodes_are_sorted_by_name(self):
        result = PipelineRunResult(pipeline="p").absorb_trace(
            [{"name": "z"}, {"name": "a"}, {"name": "m"}]
        )
        assert [n.name for n in result.nodes] == ["a", "m", "z"]

    def test_an_unknown_status_with_an_error_reads_as_failed(self):
        result = PipelineRunResult(pipeline="p").absorb_trace(
            [{"name": "n", "status": "weird", "error": "boom"}]
        )
        assert result.nodes[0].status is NodeStatus.FAILED

    def test_a_none_trace_is_harmless(self):
        assert PipelineRunResult(pipeline="p").absorb_trace(None).nodes == []

    def test_non_dict_entries_are_ignored(self):
        result = PipelineRunResult(pipeline="p").absorb_trace(["junk", {"name": "n"}])
        assert [n.name for n in result.nodes] == ["n"]


class TestPrimaryError:
    def test_explicit_errors_come_first(self):
        result = PipelineRunResult(
            pipeline="p",
            errors=["chain failed"],
            nodes=[NodeOutcome(name="n", status=NodeStatus.FAILED, error="node boom")],
        )
        assert result.primary_error == "chain failed"

    def test_falls_back_to_the_first_node_error(self):
        result = PipelineRunResult(
            pipeline="p",
            nodes=[NodeOutcome(name="n", status=NodeStatus.FAILED, error="node boom")],
        )
        assert result.primary_error == "node 'n': node boom"

    def test_a_clean_run_has_no_primary_error(self):
        assert PipelineRunResult(pipeline="p").primary_error is None


class TestSerialization:
    def test_to_dict_is_json_ready(self):
        import json

        result = PipelineRunResult(
            pipeline="p",
            status=RunStatus.GATE_BLOCKED,
            run_id="abc",
            nodes=[NodeOutcome(name="n")],
            gate_blocked={"n": {"error": "below threshold"}},
        )

        payload = json.dumps(result.to_dict())

        assert '"status": "gate_blocked"' in payload
        assert '"pipeline": "p"' in payload

    def test_status_values_are_plain_strings(self):
        # str-valued enum, so existing `== "success"` comparisons keep working.
        assert RunStatus.SUCCESS == "success"
        assert NodeStatus.FAILED == "failed"

    def test_summary_mentions_the_interesting_parts(self):
        result = PipelineRunResult(
            pipeline="sales",
            status=RunStatus.GATE_BLOCKED,
            nodes=[NodeOutcome(name="a"), NodeOutcome(name="b", status=NodeStatus.SKIPPED)],
            gate_blocked={"b": {}},
            reused_pipelines=["raw"],
        )

        summary = result.summary()

        assert "sales" in summary
        assert "gate_blocked" in summary
        assert "1/2 nodes ok" in summary
        assert "1 reused" in summary


class TestFailedNodes:
    def test_only_failures_are_listed(self):
        result = PipelineRunResult(
            pipeline="p",
            nodes=[
                NodeOutcome(name="ok"),
                NodeOutcome(name="bad", status=NodeStatus.FAILED),
                NodeOutcome(name="skipped", status=NodeStatus.SKIPPED),
            ],
        )
        assert [n.name for n in result.failed_nodes] == ["bad"]
