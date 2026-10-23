"""What `ducta stream run` and `ducta stream plan` print."""

from __future__ import annotations

import json

import pytest

from ducta.console import stream_view
from ducta.console.stream_view import (
    LiveReporter,
    render_final_summary,
    render_live_table,
    render_plan,
    render_start_summary,
)
from ducta.stream.plan import ERROR, WARNING, Issue, NodePlan, PipelinePlan

SNAPSHOT = {
    "execution_id": "6395c963662c4b9c988e1963ba137957",
    "status": "running",
    "uptime_seconds": 42,
    "total_queries": 2,
    "active_queries": 2,
    "query_statuses": {"ingest": {"isActive": True}, "clean": {"isActive": True}},
    "node_summaries": {
        "ingest": {
            "source": "file_stream json data/events",
            "sink": "parquet data/bronze",
            "trigger": "every 5 seconds",
            "output_mode": "append",
            "checkpoint": "data/_ckpt/ingest/p/ingest",
        }
    },
    "progress_metrics": {
        "ingest": {
            "batchId": 12,
            "inputRowsPerSecond": 140.0,
            "processedRowsPerSecond": 140.0,
            "triggerExecutionMs": 400,
            "numInputRows": 5,
            "idleSeconds": 0.0,
        },
        "clean": {"batchId": 11, "numInputRows": 0, "idleSeconds": 185.0},
    },
}


@pytest.fixture(autouse=True)
def _ascii(monkeypatch):
    # Same text everywhere: the glyph choice is tested on its own.
    monkeypatch.setattr(stream_view, "_utf8", lambda: False)


class TestStartSummary:
    def test_one_header_and_a_line_per_node(self):
        lines = render_start_summary(SNAPSHOT, "events", "dev").splitlines()
        assert lines[0] == "events - dev - 2 nodes running - execution 6395c963 - Ctrl+C to stop"
        ingest = next(line for line in lines if line.strip().startswith("ingest"))
        assert "file_stream json data/events  ->  parquet" not in ingest  # one space each side
        assert "file_stream json data/events -> parquet data/bronze" in ingest
        assert ingest.rstrip().endswith("every 5 s")

    def test_the_checkpoint_is_not_repeated_here(self):
        assert "checkpoint" not in render_start_summary(SNAPSHOT, "events", "dev")

    def test_a_node_without_a_summary_is_still_listed(self):
        assert "  clean" in render_start_summary(SNAPSHOT, "events", "dev").splitlines()

    def test_nodes_not_all_up_are_counted_as_such(self):
        snap = {**SNAPSHOT, "active_queries": 1, "total_queries": 4}
        assert "1 of 4 nodes running" in render_start_summary(snap, "events", "dev")

    def test_unicode_terminals_get_the_nicer_glyphs(self, monkeypatch):
        monkeypatch.setattr(stream_view, "_utf8", lambda: True)
        text = render_start_summary(SNAPSHOT, "events", "dev")
        assert "→" in text and "·" in text

    def test_triggers_are_abbreviated(self):
        assert stream_view.short_trigger("every 5 seconds") == "every 5 s"
        assert stream_view.short_trigger("every 1 second") == "every 1 s"
        assert stream_view.short_trigger("every 2 minutes") == "every 2 min"
        assert stream_view.short_trigger("every 1 hour") == "every 1 h"
        assert stream_view.short_trigger("every 500 milliseconds") == "every 500 ms"
        assert stream_view.short_trigger("available_now") == "available_now"


class TestLiveTable:
    def test_one_row_per_node_with_state_rate_and_batch(self):
        text = render_live_table(SNAPSHOT)
        assert text.splitlines()[0] == "* running - up 00:42"
        assert "Ctrl+C" not in text  # said once, in the start header
        header = text.splitlines()[1].split()
        assert header == ["NODE", "STATE", "ROWS/s", "BATCH"]
        row = next(line for line in text.splitlines() if line.strip().startswith("ingest"))
        assert row.split() == ["ingest", "active", "140/s", "12"]

    def test_the_input_rate_shows_only_when_the_node_falls_behind(self):
        snap = {**SNAPSHOT}
        snap["progress_metrics"] = {
            "ingest": {
                "batchId": 3,
                "inputRowsPerSecond": 300.0,
                "processedRowsPerSecond": 140.0,
                "numInputRows": 5,
                "idleSeconds": 0.0,
            },
        }
        assert "140/s (in 300/s)" in render_live_table(snap)
        snap["progress_metrics"]["ingest"]["inputRowsPerSecond"] = 150.0  # keeping up
        assert "(in " not in render_live_table(snap)
        snap["progress_metrics"]["ingest"].update(
            inputRowsPerSecond=3.0, processedRowsPerSecond=1.0
        )
        assert "(in " not in render_live_table(snap)  # too small to matter

    def test_a_quiet_source_is_said_to_be_idle_not_broken(self):
        text = render_live_table(SNAPSHOT)
        assert "active, idle 3m" in text
        assert "clean: no new input for 3m (a quiet source, not a failure)" in text
        assert "! clean" not in text

    def test_a_failed_node_names_how_many_failed_and_why(self):
        snap = {
            **SNAPSHOT,
            "status": "partial_failure",
            "query_statuses": {
                "ingest": {"isActive": False, "exception": "AnalysisException: x"},
                "clean": {"isActive": True},
            },
        }
        text = render_live_table(snap)
        assert text.splitlines()[0] == "! 1 of 2 nodes failed - up 00:42"
        assert "! ingest: AnalysisException: x" in text

    def test_skipped_nodes_are_counted_too(self):
        snap = {
            **SNAPSHOT,
            "status": "partial_failure",
            "query_statuses": {"ingest": {"isActive": False, "exception": "boom"}},
            "skipped_nodes": {"clean": "upstream failed"},
        }
        assert (
            render_live_table(snap).splitlines()[0].startswith("! 1 of 2 nodes failed, 1 skipped")
        )

    def test_a_stall_is_flagged(self):
        snap = {
            **SNAPSHOT,
            "health_monitors": {"ingest": {"error": "Query stalled: no progress for 400s"}},
        }
        text = render_live_table(snap)
        assert "stalled" in text and "may be hung" in text


class TestLiveReporter:
    def test_first_look_then_only_when_due_or_changed(self):
        now = [0.0]
        reporter = LiveReporter(interval=30, clock=lambda: now[0])
        assert reporter.tick(SNAPSHOT) is not None  # the first look
        now[0] = 5
        assert reporter.tick(SNAPSHOT) is None
        now[0] = 31
        assert reporter.tick(SNAPSHOT) is not None  # due

    def test_no_table_of_dashes_before_a_node_has_reported(self):
        silent = {**SNAPSHOT, "progress_metrics": {}}
        now = [0.0]
        reporter = LiveReporter(interval=30, clock=lambda: now[0])
        assert reporter.tick(silent) is None
        now[0] = 5
        assert reporter.tick(silent) is None
        assert reporter.tick(SNAPSHOT) is not None  # the first report arrives: print at once

    def test_but_it_does_not_wait_forever_for_a_node_that_never_reports(self):
        silent = {**SNAPSHOT, "progress_metrics": {}}
        now = [0.0]
        reporter = LiveReporter(interval=30, clock=lambda: now[0])
        reporter.tick(silent)
        now[0] = stream_view.FIRST_REPORT_WAIT_SECONDS + 1
        assert reporter.tick(silent) is not None

    def test_a_failure_before_any_report_is_not_held_back(self):
        silent = {**SNAPSHOT, "progress_metrics": {}}
        now = [0.0]
        reporter = LiveReporter(interval=30, clock=lambda: now[0])
        reporter.tick(silent)
        now[0] = 2
        failing = {
            **silent,
            "query_statuses": {
                "ingest": {"isActive": False, "exception": "boom"},
                "clean": {"isActive": True},
            },
        }
        assert "! ingest: boom" in reporter.tick(failing)

    def test_a_node_changing_state_prints_at_once(self):
        now = [0.0]
        reporter = LiveReporter(interval=30, clock=lambda: now[0])
        reporter.tick(SNAPSHOT)
        now[0] = 2
        failing = {
            **SNAPSHOT,
            "query_statuses": {
                "ingest": {"isActive": False, "exception": "boom"},
                "clean": {"isActive": True},
            },
        }
        assert "! ingest: boom" in reporter.tick(failing)
        now[0] = 3
        assert reporter.tick(failing) is None  # unchanged since

    def test_the_interval_can_be_set_from_the_environment(self, monkeypatch):
        monkeypatch.setenv(stream_view.REPORT_SECONDS_ENV, "7")
        assert LiveReporter().interval == 7.0
        monkeypatch.setenv(stream_view.REPORT_SECONDS_ENV, "nonsense")
        assert LiveReporter().interval == stream_view.DEFAULT_REPORT_SECONDS


def _plan(*, error=False, warning=False):
    node = NodePlan(
        "a",
        "file_stream json in",
        "parquet out",
        "every 5 seconds",
        "append",
        "ck/p/a",
        after=["z"],
        transform="t",
    )
    if error:
        node.issues.append(Issue(ERROR, "transform 't' is not registered"))
    if warning:
        node.issues.append(Issue(WARNING, "source path 'in' does not exist yet"))
    return PipelinePlan("p", "dev", [node])


class TestPlanRendering:
    def test_a_clean_plan(self):
        text = render_plan(_plan())
        assert "Plan - p - env dev - nothing was started" in text
        assert "a  (after z)" in text
        for line in (
            "reads       file_stream json in",
            "writes      parquet out",
            "transform   t",
            "fires       every 5 seconds - append",
            "checkpoint  ck/p/a",
        ):
            assert line in text
        assert text.rstrip().endswith("Ready: 1 node, no problems found.")

    def test_warnings_do_not_block(self):
        text = render_plan(_plan(warning=True))
        assert "! source path 'in' does not exist yet" in text
        assert text.rstrip().endswith("Ready: 1 node, 1 warning.")

    def test_errors_say_to_fix_them(self):
        text = render_plan(_plan(error=True))
        assert "x transform 't' is not registered" in text
        assert text.rstrip().endswith("1 error, 0 warnings: fix the errors before starting.")

    def test_json_form_is_machine_readable(self):
        assert json.loads(json.dumps(_plan(error=True).to_dict()))["ok"] is False


class TestFormatting:
    def test_rates_and_durations(self):
        assert stream_view.format_rate(None) == "-"
        assert stream_view.format_rate(2345) == "2.3k/s"
        assert stream_view.format_rate(0.537) == "0.54/s"
        assert stream_view.format_duration(185) == "3m"
        assert stream_view.format_duration(3900) == "1h 5m"
        assert stream_view.format_uptime(42) == "00:42"
        assert stream_view.format_uptime(3669) == "1:01:09"


class TestClosingSummary:
    DONE = {
        "status": "stopped",
        "uptime_seconds": 105,
        "query_statuses": {"ingest": {"isActive": False}, "clean": {"isActive": False}},
        "node_order": ["ingest", "clean"],
        "totals": {
            "ingest": {"rows": 12340.0, "batches": 24},
            "clean": {"rows": 118.0, "batches": 23},
        },
    }

    def test_it_says_how_long_it_ran_and_what_each_node_processed(self):
        lines = render_final_summary(self.DONE).splitlines()
        assert lines[0] == "Stopped - ran 01:45"
        assert "BATCHES" in lines[1] and "ROWS IN" in lines[1]
        ingest = next(line for line in lines if line.strip().startswith("ingest"))
        assert "24" in ingest and "12,340" in ingest and ingest.rstrip().endswith("stopped")
        assert any("118" in line for line in lines)

    def test_a_run_that_ended_on_its_own_is_finished(self):
        assert render_final_summary({**self.DONE, "status": "completed"}).startswith("Finished")

    def test_a_run_that_ended_badly_says_so(self):
        snap = {
            **self.DONE,
            "status": "partial_failure",
            "query_statuses": {
                "ingest": {"isActive": False, "exception": "boom"},
                "clean": {"isActive": False},
            },
        }
        assert render_final_summary(snap).startswith("Ended: 1 of 2 nodes failed - ran")

    def test_a_node_without_figures_shows_dashes(self):
        text = render_final_summary({**self.DONE, "totals": {}})
        assert text.splitlines()[2].split()[1:3] == ["-", "-"]

    def test_nothing_to_report_prints_nothing(self):
        assert render_final_summary({"status": "stopped"}) == ""
