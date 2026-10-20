"""The CLI's compact view: what the terminal shows, and what it no longer shows.

The classic log — every line as it happens — is the default. The compact view
(``DUCTA_CONSOLE=compact``) is a header, one line per node, a summary, and one
error block that says where and what next; the log file still gets everything.
"""

from __future__ import annotations

import argparse
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.console.cli import UnifiedCLI, _wants_compact
from ducta.console.core import ExitCode
from ducta.console.parser import COMMAND_GROUPS, GROUP_EXAMPLES, UnifiedArgumentParser
from ducta.console.ux import view
from ducta.console.ux.rich_logger import _compact_filter


@contextmanager
def _cwd(path: Path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@pytest.fixture
def compact():
    view.set_mode(compact=True)
    yield view
    view.set_mode(compact=False)


def _record(name: str, level: str, **extra):
    levels = {"DEBUG": 10, "INFO": 20, "SUCCESS": 25, "WARNING": 30, "ERROR": 40}
    return {
        "name": name,
        "level": SimpleNamespace(name=level, no=levels[level]),
        "extra": extra,
    }


class TestWhatTheTerminalShows:
    def test_engine_info_goes_to_the_log_file_only(self):
        assert not _compact_filter(_record("ducta.setting.session", "INFO"))
        assert not _compact_filter(_record("ducta.core.resource_manager", "INFO"))

    def test_engine_warnings_and_errors_are_shown(self):
        assert _compact_filter(_record("ducta.gate.input", "WARNING"))
        assert _compact_filter(_record("ducta.core.executors.facade", "ERROR"))

    def test_the_clis_own_messages_are_shown(self):
        assert _compact_filter(_record("ducta.console.commands.config_cmds", "INFO"))

    def test_what_the_users_node_code_logs_is_shown(self):
        assert _compact_filter(_record("pipelines.etl", "INFO"))

    def test_a_node_error_is_left_to_the_error_block(self):
        assert not _compact_filter(_record("ducta.core.commands", "ERROR", node_error=True))
        assert not _compact_filter(_record("ducta.console.cli", "ERROR", console=False))


class TestNodeLines:
    def test_a_finished_node_names_its_rows_output_time_and_checks(self, compact, capsys):
        view.reset_run(["extract"], ["bronze.raw"])
        view.quality_report(
            SimpleNamespace(
                dataset_name="extract",
                results=[SimpleNamespace(passed=True), SimpleNamespace(passed=True)],
            )
        )
        view.node_finished("extract", 0.71, [("bronze.raw", 508)])
        err = capsys.readouterr().err
        assert "✓ extract" in err
        assert "508 rows → bronze.raw" in err
        assert "0.7s" in err and "2 checks passed" in err

    def test_a_failed_node_is_reported_once(self, compact, capsys):
        view.reset_run(["transform"])
        error = ValueError("boom")
        view.node_failed("transform", error)
        view.node_failed("transform", error)  # the runner and the coordinator both report it
        assert capsys.readouterr().err.count("✗ transform") == 1

    def test_a_failing_check_is_printed_under_its_node(self, compact, capsys):
        view.reset_run(["transform"])
        view.quality_report(
            SimpleNamespace(
                dataset_name="transform",
                results=[
                    SimpleNamespace(passed=True),
                    SimpleNamespace(
                        passed=False, check_name="row_count", message="12 < 400", is_error=True
                    ),
                ],
            )
        )
        err = capsys.readouterr().err
        assert "row_count" in err and "12 < 400" in err

    def test_quiet_prints_no_node_lines(self, capsys):
        view.set_mode(compact=True, quiet=True)
        try:
            view.reset_run(["a"])
            view.node_finished("a", 1.0, [])
        finally:
            view.set_mode(compact=False)
        assert capsys.readouterr().err == ""


class TestSummary:
    def test_success_names_the_certificate_and_how_to_inspect_it(self, compact, capsys):
        result = SimpleNamespace(
            pipeline="etl",
            nodes=[SimpleNamespace(ok=True)] * 3,
            gate_blocked={},
            skipped={},
            reused_pipelines=[],
            certificate_path="data/dev/.ducta/runs/abc/certificate.json",
            certificate_error=None,
            run_id="abcdef1234567890",
        )
        view.print_run_summary(result, 4.5)
        err = capsys.readouterr().err
        assert "✓ etl finished in 4.5s · 3/3 nodes" in err
        assert "ducta certify show --run-id abcdef12" in err

    def test_a_blocked_gate_is_not_a_success(self, compact, capsys):
        result = SimpleNamespace(
            pipeline="etl",
            nodes=[],
            gate_blocked={"transform": {"error": "nulls in amount"}},
            skipped={"load": "upstream blocked"},
            reused_pipelines=[],
            certificate_path=None,
            certificate_error=None,
            run_id=None,
        )
        view.print_run_summary(result, 1.0)
        err = capsys.readouterr().err
        assert "did not finish: a quality gate blocked it" in err
        assert "transform — nulls in amount" in err and "load — upstream blocked" in err


def _raise_in(path: Path, exc: Exception):
    """Raise *exc* from code compiled as *path*: a frame in "the user's file"."""
    code = compile("def node():\n    raise EXC\n", str(path), "exec")
    scope = {"EXC": exc}
    exec(code, scope)
    scope["node"]()


class TestFailureBlock:
    def test_names_the_users_line_the_hint_and_what_to_run(self, compact, capsys, tmp_path):
        from ducta.core.errors import PipelineExecutionError

        (tmp_path / "pipelines").mkdir()
        user_file = tmp_path / "pipelines" / "etl.py"
        cause = Exception(
            "[UNRESOLVED_COLUMN.WITH_SUGGESTION] A column or function parameter with name "
            "`ammount` cannot be resolved. Did you mean one of the following? [`amount`, "
            "`category`]."
        )
        try:
            _raise_in(user_file, cause)
        except Exception as caught:
            cause = caught
        error = PipelineExecutionError(
            pipeline="etl", message="failed", failed_nodes=["transform"], cause=cause
        )
        view.reset_run(["extract", "transform", "load"])
        view.node_finished("extract", 0.5, [])
        with _cwd(tmp_path):
            view.print_run_failure(
                error,
                pipeline="etl",
                env="dev",
                project=tmp_path,
                all_nodes=["extract", "transform", "load"],
                log_file=str(tmp_path / "logs" / "ducta.log"),
            )
        err = capsys.readouterr().err
        assert "✗ transform failed: Column 'ammount' does not exist" in err
        assert "did you mean 'amount'?" in err
        assert "pipelines/etl.py:2" in err
        assert "not run  load" in err
        assert "ducta start -e dev -p etl -n transform" in err
        assert "ducta ai explain --error-file logs/last-error.txt" in err
        assert (tmp_path / "logs" / "last-error.txt").is_file()

    def test_the_run_result_travels_with_the_exception(self):
        from ducta.core.errors import PipelineExecutionError

        inner = ValueError("x")
        inner.run_result = SimpleNamespace(run_id="r1")  # type: ignore[attr-defined]
        outer = PipelineExecutionError(pipeline="p", cause=inner)
        assert view.run_result_of(outer).run_id == "r1"


class TestModeSelection:
    def _args(self, argv):
        return UnifiedArgumentParser.create().parse_args(argv)

    def test_the_classic_log_is_the_default(self, monkeypatch):
        monkeypatch.delenv("DUCTA_CONSOLE", raising=False)
        assert not _wants_compact(self._args(["start", "-p", "etl"]))

    def test_compact_only_when_asked(self, monkeypatch):
        monkeypatch.setenv("DUCTA_CONSOLE", "compact")
        assert _wants_compact(self._args(["start", "-p", "etl"]))

    @pytest.mark.parametrize(
        "argv",
        [
            ["-v", "start", "-p", "etl"],
            ["start", "-p", "etl", "--verbose"],
            ["start", "-p", "etl", "--log-level", "DEBUG"],
            ["ui"],
        ],
    )
    def test_every_line_when_asked_or_for_a_server(self, argv, monkeypatch):
        monkeypatch.setenv("DUCTA_CONSOLE", "compact")
        assert not _wants_compact(self._args(argv))

    def test_the_cli_leaves_the_process_as_it_found_it(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DUCTA_CONSOLE", "compact")
        monkeypatch.delenv("DUCTA_SPARK_QUIET", raising=False)
        with _cwd(tmp_path):
            UnifiedCLI().run([])
        assert not view.is_compact()
        assert "DUCTA_SPARK_QUIET" not in os.environ


class TestEntryPoints:
    def test_ducta_alone_says_how_to_start(self, tmp_path, capsys):
        with _cwd(tmp_path):
            assert UnifiedCLI().run([]) == ExitCode.SUCCESS.value
        out = capsys.readouterr().err
        assert "no project here" in out and "ducta init project --name" in out

    def test_version_is_one_plain_line(self, capsys):
        from ducta import __version__

        assert UnifiedCLI().run(["--version"]) == 0
        assert capsys.readouterr().out == f"ducta {__version__}\n"

    def test_a_group_without_its_command_lists_them(self, capsys):
        with pytest.raises(SystemExit) as exit_info:
            UnifiedArgumentParser.create().parse_args(["config"])
        assert exit_info.value.code == 2
        err = capsys.readouterr().err
        assert "which command?" in err and "validate" in err
        assert "config_command" not in err

    def test_every_command_is_in_the_grouped_help(self):
        parser = UnifiedArgumentParser.create()
        grouped = [name for _, cmds in COMMAND_GROUPS for name, _ in cmds]
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        assert sorted(grouped) == sorted(sub.choices)
        help_text = parser.format_help()
        assert all(f"  {name} " in help_text for name in grouped)

    def test_every_group_has_an_example_that_parses(self):
        import shlex

        assert set(GROUP_EXAMPLES) == {group for group, _ in COMMAND_GROUPS}
        parser = UnifiedArgumentParser.create()
        for group, example in GROUP_EXAMPLES.items():
            argv = shlex.split(example)
            assert argv[0] == "ducta", group
            parser.parse_args(argv[1:])  # SystemExit here: the example went stale
            assert f"e.g.         {example}" in parser.format_help()

    def test_env_and_pipeline_have_short_forms_everywhere(self):
        args = UnifiedArgumentParser.create().parse_args(
            ["config", "validate", "-e", "dev", "-p", "etl"]
        )
        assert (args.env, args.pipeline) == ("dev", "etl")


class TestSparkQuiet:
    def test_only_when_the_cli_asks(self, monkeypatch):
        from ducta.setting.session import _quiet_log4j_file

        monkeypatch.delenv("DUCTA_SPARK_QUIET", raising=False)
        assert _quiet_log4j_file() is None
        monkeypatch.setenv("DUCTA_SPARK_QUIET", "1")
        path = _quiet_log4j_file()
        text = path.read_text(encoding="utf-8")
        # Equal levels: Spark prints "Setting default log level" when they differ.
        assert "rootLogger.level = fatal" in text and "logger.spark.level = fatal" in text
