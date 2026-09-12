"""``--validate-only`` must actually validate.

It built the ``Context`` — schema validation — and stopped, then reported
"Configuration validation successful". It accepted ``--pipeline`` and never
looked at it, so everything ``ducta.core.preflight`` exists to catch went
straight through: an unregistered check name, a node function that cannot be
imported, an output key missing from the catalog, a dependency cycle, a gate
behavior that silently falls back to another one.

That is the wrong way for a pre-run check to be wrong. It is the command people
put in CI and in a pre-presentation script precisely so a config error surfaces
before a run; one that cannot fail buys nothing and is trusted anyway.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ducta.console.commands.execution_cmds import ExecutionCommands
from ducta.console.core import ExitCode
from ducta.core.preflight import PreflightReport


class _Ctx:
    env = "dev"
    pipelines = {"etl": {"nodes": ["a"]}}
    nodes_config = {"a": {}}


def _command(pipeline=None):
    command = ExecutionCommands.__new__(ExecutionCommands)
    command.config = SimpleNamespace(env="dev", pipeline=pipeline)
    return command


class _Init:
    def initialize(self, env):
        return _Ctx()


class TestPreflightDecidesTheExitCode:
    def test_a_clean_config_passes(self, monkeypatch):
        monkeypatch.setattr(
            ExecutionCommands,
            "_run_preflight_report",
            lambda self, ctx: PreflightReport(pipeline_name="etl"),
        )

        assert _command("etl")._handle_validate_only(_Init()) == ExitCode.SUCCESS.value

    def test_a_preflight_error_fails_the_command(self, monkeypatch):
        """The whole point: a config preflight rejects must not report success."""
        report = PreflightReport(pipeline_name="etl")
        report.error("Node 'a': output 'x' is not registered in the output catalog")
        monkeypatch.setattr(ExecutionCommands, "_run_preflight_report", lambda self, ctx: report)

        assert _command("etl")._handle_validate_only(_Init()) == ExitCode.VALIDATION_ERROR.value

    def test_warnings_alone_do_not_fail(self, monkeypatch):
        """Preflight warnings are advisory — they must not break a CI gate."""
        report = PreflightReport(pipeline_name="etl")
        report.warn("Node 'a': ['typo'] are not node configuration keys")
        monkeypatch.setattr(ExecutionCommands, "_run_preflight_report", lambda self, ctx: report)

        assert _command("etl")._handle_validate_only(_Init()) == ExitCode.SUCCESS.value

    def test_a_checker_that_cannot_run_does_not_fail_a_valid_config(self, monkeypatch):
        """A bug in preflight must not turn a good config into a failed build."""
        monkeypatch.setattr(ExecutionCommands, "_run_preflight_report", lambda self, ctx: None)

        assert _command("etl")._handle_validate_only(_Init()) == ExitCode.SUCCESS.value


class TestWhichPipelinesAreChecked:
    def test_a_named_pipeline_is_checked_on_its_own(self, monkeypatch):
        seen = {}

        def fake_validate_pipeline(context, pipeline_name):
            seen["pipeline"] = pipeline_name
            return PreflightReport(pipeline_name=pipeline_name)

        monkeypatch.setattr("ducta.core.preflight.validate_pipeline", fake_validate_pipeline)

        _command("etl")._run_preflight_report(_Ctx())

        assert seen["pipeline"] == "etl"

    def test_without_a_pipeline_every_one_is_checked(self, monkeypatch):
        failing = PreflightReport(pipeline_name="other")
        failing.error("boom")
        monkeypatch.setattr(
            "ducta.core.preflight.validate_all_pipelines",
            lambda context: {"etl": PreflightReport(pipeline_name="etl"), "other": failing},
        )

        report = _command(None)._run_preflight_report(_Ctx())

        assert not report.ok
        assert any("[other]" in e for e in report.errors), "findings must name their pipeline"

    def test_a_raising_checker_is_swallowed(self, monkeypatch):
        def boom(context, pipeline_name):
            raise RuntimeError("checker bug")

        monkeypatch.setattr("ducta.core.preflight.validate_pipeline", boom)

        assert _command("etl")._run_preflight_report(_Ctx()) is None
