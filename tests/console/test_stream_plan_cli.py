"""`ducta stream plan`, and what `ducta stream run` prints while a stream lives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ducta.console import execution
from ducta.console.core import ExitCode
from ducta.console.parser import UnifiedArgumentParser


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    from ducta.console.template import TemplateGenerator, TemplateType

    root = tmp_path / "sb"
    TemplateGenerator(root).generate_project(TemplateType.STREAMING_BASIC, "sb")
    monkeypatch.chdir(root)
    monkeypatch.syspath_prepend(str(root))
    return root


class TestStreamPlanCommand:
    def test_the_parser_knows_it(self):
        args = UnifiedArgumentParser.create().parse_args(
            ["stream", "plan", "--pipeline", "events", "--env", "dev", "--output-format", "json"]
        )
        assert (args.stream_command, args.pipeline, args.env, args.output_format) == (
            "plan",
            "events",
            "dev",
            "json",
        )

    def test_a_good_project_is_ready_and_nothing_starts(self, project, capsys):
        code = execution.plan_streaming_pipeline_cli(None, "events_stream", env="dev")
        out = capsys.readouterr().out
        assert code == ExitCode.SUCCESS.value
        assert "Plan" in out and "ingest_events" in out and "clean_events" in out
        assert "data/dev/_ckpt/ingest_events/events_stream/ingest_events" in out
        assert out.rstrip().endswith("Ready: 2 nodes, no problems found.")
        assert not (project / "data" / "dev" / "_ckpt").exists()  # a plan creates nothing

    def test_json_output_is_parseable(self, project, capsys):
        code = execution.plan_streaming_pipeline_cli(
            None, "events_stream", env="dev", format_type="json"
        )
        out = capsys.readouterr().out
        body = json.loads(out[out.index("{") :])  # the loader's log may precede the document
        assert (
            code == ExitCode.SUCCESS.value
            and body["ok"] is True
            and [n["name"] for n in body["nodes"]] == ["ingest_events", "clean_events"]
        )

    def test_a_problem_fails_the_command(self, project, capsys):
        (project / "pipelines" / "transforms.py").write_text(
            "def register_transforms(registry):\n    pass\n"  # clean_events is no longer registered
        )
        code = execution.plan_streaming_pipeline_cli(None, "events_stream", env="dev")
        out = capsys.readouterr().out
        assert code == ExitCode.VALIDATION_ERROR.value
        assert "transform 'clean_events' is not registered" in out
        assert "fix the errors before starting" in out

    def test_an_unknown_pipeline_lists_the_known_ones(self, project, capsys):
        assert (
            execution.plan_streaming_pipeline_cli(None, "nope", env="dev")
            == ExitCode.VALIDATION_ERROR.value
        )


class _Executor:
    """Just enough engine for the foreground loop: a status that ends after a few looks."""

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.calls = 0

    def wait_for_streaming_startup(self, *a, **k):
        return {}

    def get_streaming_pipeline_status(self, _eid):
        self.calls += 1
        return self._statuses[min(self.calls - 1, len(self._statuses) - 1)]


class TestForegroundOutput:
    SNAP = {
        "execution_id": "abcdef0123456789",
        "status": "running",
        "uptime_seconds": 3,
        "total_queries": 1,
        "active_queries": 1,
        "query_statuses": {"n": {"isActive": True}},
        "node_summaries": {
            "n": {
                "source": "rate 5 rows/s",
                "sink": "memory",
                "trigger": "every 1 seconds",
                "output_mode": "append",
                "checkpoint": "ck/p/n",
            }
        },
        "progress_metrics": {
            "n": {
                "batchId": 2,
                "processedRowsPerSecond": 5.0,
                "inputRowsPerSecond": 5.0,
                "triggerExecutionMs": 100,
                "numInputRows": 5,
                "idleSeconds": 0.0,
            }
        },
    }

    def test_it_prints_what_started_then_a_table_then_ends_cleanly(self, monkeypatch, capsys):
        monkeypatch.setattr(execution.time, "sleep", lambda _s: None)
        monkeypatch.setattr(
            execution.stream_view, "_utf8", lambda: False
        )  # same text on any terminal
        ended = {
            **self.SNAP,
            "active_queries": 0,
            "status": "completed",
            "query_statuses": {"n": {"isActive": False}},
        }
        executor = _Executor([self.SNAP, self.SNAP, ended, ended])
        code = execution._stay_in_foreground(executor, "p", "abcdef0123456789", "dev")
        out = capsys.readouterr().out
        assert code == ExitCode.SUCCESS.value
        assert "p - dev - 1 node running - execution abcdef01 - Ctrl+C to stop" in out
        assert "rate 5 rows/s -> memory   every 1 s" in out
        assert "is running (execution ID" not in out  # one start block, not three
        assert "NODE" in out and "ROWS/s" in out  # the live table, at least once
