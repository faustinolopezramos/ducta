"""What `ducta <cmd>` exits with, per class of failure.

`UnifiedCLI.run` had no tests at all, and it caught only
`ducta.console.core.DuctaError` — a class unrelated to the one the engine
raises. Everything from `ducta.core` therefore fell through to the catch-all,
printed "Unexpected error", and exited 1: a mistyped pipeline name, a failed
preflight and a genuine crash were indistinguishable to any script wrapping the
CLI, even though each engine error already declared the exit code it deserved.

The two hierarchies are now one, so these pin the mapping end to end.
"""

from __future__ import annotations

import pytest

from ducta.console.cli import UnifiedCLI
from ducta.console.core import ExitCode, ValidationError


@pytest.fixture
def cli(monkeypatch):
    """A CLI whose `start` handler raises whatever a test hands it."""
    instance = UnifiedCLI()

    def _run_raising(exc):
        def handler(_args):
            raise exc

        monkeypatch.setattr(
            instance,
            "_build_dispatch_table",
            lambda: {"start": (None, handler)},
        )
        return instance.run(["start", "--env", "base", "--pipeline", "p"])

    return _run_raising


class TestEngineErrorsKeepTheirExitCode:
    def test_a_missing_pipeline_exits_as_a_configuration_error(self, cli):
        from ducta.core.errors import PipelineNotFoundError

        assert cli(PipelineNotFoundError("nope", ["a", "b"])) == ExitCode.CONFIGURATION_ERROR.value

    def test_a_failed_preflight_exits_as_a_configuration_error(self, cli):
        from ducta.core.errors import PreflightError

        assert cli(PreflightError("p", ["missing node config"])) == (
            ExitCode.CONFIGURATION_ERROR.value
        )

    def test_a_failed_run_exits_as_an_execution_error(self, cli):
        from ducta.core.errors import PipelineExecutionError

        assert cli(PipelineExecutionError("p", "boom")) == ExitCode.EXECUTION_ERROR.value

    def test_a_node_timeout_exits_as_an_execution_error(self, cli):
        from ducta.core.errors import NodeTimeoutError

        assert cli(NodeTimeoutError("slow", 30)) == ExitCode.EXECUTION_ERROR.value

    def test_bad_data_exits_as_an_execution_error(self, cli):
        from ducta.core.errors import SanityCheckFailedError

        assert cli(SanityCheckFailedError("clean", 3)) == ExitCode.EXECUTION_ERROR.value


class TestConsoleErrorsStillWork:
    def test_a_console_validation_error_exits_as_a_validation_error(self, cli):
        assert cli(ValidationError("bad argument")) == ExitCode.VALIDATION_ERROR.value

    def test_a_console_configuration_error_exits_as_a_configuration_error(self, cli):
        from ducta.console.core import ConfigurationError

        assert cli(ConfigurationError("no config found")) == ExitCode.CONFIGURATION_ERROR.value


class TestEverythingElse:
    def test_an_unexpected_error_is_still_a_general_error(self, cli):
        # Genuine bugs must not be dressed up as one of the known categories.
        assert cli(TypeError("a real bug")) == ExitCode.GENERAL_ERROR.value

    def test_an_interrupt_is_a_general_error(self, cli):
        assert cli(KeyboardInterrupt()) == ExitCode.GENERAL_ERROR.value


class TestExitCodesAgreeAcrossTheTwoHierarchies:
    def test_the_engine_and_the_console_use_the_same_numbers(self):
        from ducta.console.core import ConfigurationError as ConsoleConfigError
        from ducta.core.errors import ConfigurationError as EngineConfigError

        assert EngineConfigError("x").exit_code == ConsoleConfigError("x").exit_code
        assert EngineConfigError("x").exit_code == ExitCode.CONFIGURATION_ERROR.value


class TestTheWrapperPropagatesTheExitCode:
    """The console script is `sys.exit(wrapper.main())`, so main must return it.

    `wrapper.main()` called the CLI and dropped what it returned, so the entry
    point evaluated `sys.exit(None)` and *every* failure exited 0 — no script
    wrapping `ducta` could tell a broken run from a clean one, and the whole
    exit-code taxonomy was invisible at the process boundary.
    """

    def test_the_cli_return_value_is_returned(self, monkeypatch):
        from ducta.console import cli as cli_module
        from ducta.console import wrapper

        monkeypatch.setattr(cli_module, "main", lambda: ExitCode.EXECUTION_ERROR.value)

        assert wrapper.main() == ExitCode.EXECUTION_ERROR.value

    def test_success_is_returned_too(self, monkeypatch):
        from ducta.console import cli as cli_module
        from ducta.console import wrapper

        monkeypatch.setattr(cli_module, "main", lambda: ExitCode.SUCCESS.value)

        assert wrapper.main() == ExitCode.SUCCESS.value

    def test_a_missing_optional_dependency_reports_a_general_error(self, monkeypatch):
        from ducta.console import cli as cli_module
        from ducta.console import wrapper

        def _boom():
            raise ModuleNotFoundError("No module named 'pyspark'")

        monkeypatch.setattr(cli_module, "main", _boom)

        assert wrapper.main() == ExitCode.GENERAL_ERROR.value


class TestProjectProblemsAreConfigurationErrors:
    """Against real directories: what a script sees when there is no usable project."""

    @pytest.fixture
    def run_in(self, monkeypatch):
        def _run(directory, *argv):
            monkeypatch.chdir(directory)
            return UnifiedCLI().run(list(argv))

        return _run

    def test_no_project(self, tmp_path, run_in):
        assert run_in(tmp_path, "start", "--pipeline", "etl") == ExitCode.CONFIGURATION_ERROR.value

    @pytest.mark.parametrize(
        "argv", [["start", "--pipeline", "etl"], ["config", "validate"]], ids=["start", "validate"]
    )
    def test_an_invalid_configuration(self, tmp_path, run_in, argv):
        (tmp_path / "pipelines").mkdir()
        (tmp_path / "ducta.yaml").write_text(
            "version: 2\nproject: p\npaths: {input: data, output: data}\n"
        )
        (tmp_path / "pipelines" / "etl.yaml").write_text("nodes:\n  a: {run: 'm:f', timout: 1}\n")
        assert run_in(tmp_path, *argv) == ExitCode.CONFIGURATION_ERROR.value
