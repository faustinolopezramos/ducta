"""Where CLI commands find their project, and where their relative paths land.

Regressions from the console review of 2026-10-16, each checked against a real
scaffolded project:

* ``config --base-path`` worked only before the subcommand;
* ``config convert --out`` wrote relative to the project root, not the cwd;
* ``config pipeline-info`` exited 0 for a pipeline that does not exist;
* ``start --node`` with an unknown node warned, ran, and failed inside the run;
* ``ducta ai`` did not find the project from one of its subfolders;
* ``ducta ui`` did not detect TOML or JSON projects;
* ``certify`` had no ``--base-path`` and never searched declared environments.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.console.cli import UnifiedCLI
from ducta.console.core import ExitCode
from ducta.console.parser import UnifiedArgumentParser


@contextmanager
def _cwd(path: Path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("ws") / "demo"
    rc = UnifiedCLI().run(
        [
            "template",
            "--template",
            "medallion_basic",
            "--project-name",
            "demo",
            "--output-path",
            str(root),
        ]
    )
    assert rc == 0
    (root / "pipelines").mkdir(exist_ok=True)
    return root


def _parse(argv):
    return UnifiedArgumentParser.create().parse_args(argv)


class TestConfigBasePath:
    def test_accepted_before_and_after_the_subcommand(self):
        assert _parse(["config", "--base-path", "A", "validate"]).base_path == "A"
        assert _parse(["config", "validate", "--base-path", "B"]).base_path == "B"
        assert _parse(["config", "validate"]).base_path is None

    def test_validate_with_base_path_after_the_subcommand_runs(self, project):
        with _cwd(project.parent):
            rc = UnifiedCLI().run(["config", "validate", "--base-path", project.name])
        assert rc == ExitCode.SUCCESS.value


class TestConvertOut:
    def test_a_relative_out_is_relative_to_where_the_user_stands(self, project):
        here = project / "notes"  # a subfolder the project loader does not read
        here.mkdir(exist_ok=True)
        with _cwd(here):
            rc = UnifiedCLI().run(["config", "convert", "--to", "json", "--out", "converted"])
        assert rc == ExitCode.SUCCESS.value
        assert (here / "converted").is_dir()
        assert not (project / "converted").exists()


class TestPipelineInfo:
    def test_an_unknown_pipeline_is_an_error(self, project):
        with _cwd(project):
            rc = UnifiedCLI().run(["config", "pipeline-info", "--pipeline", "nope"])
        assert rc == ExitCode.VALIDATION_ERROR.value

    def test_a_known_pipeline_succeeds(self, project):
        with _cwd(project):
            rc = UnifiedCLI().run(["config", "pipeline-info", "--pipeline", "etl"])
        assert rc == ExitCode.SUCCESS.value


class TestUnknownNode:
    def test_fails_before_running(self, project):
        with _cwd(project):
            rc = UnifiedCLI().run(
                ["start", "--env", "dev", "--pipeline", "etl", "--node", "transfrom", "--dry-run"]
            )
        assert rc == ExitCode.VALIDATION_ERROR.value

    def test_a_node_of_the_pipeline_is_accepted(self, project):
        with _cwd(project):
            rc = UnifiedCLI().run(
                ["start", "--env", "dev", "--pipeline", "etl", "--node", "transform", "--dry-run"]
            )
        assert rc == ExitCode.SUCCESS.value


class TestAiFindsTheProjectUpward:
    def test_from_a_subfolder(self, project):
        from ducta.console.commands.ai_cmds import _project_root

        with _cwd(project / "pipelines"):
            found = _project_root(SimpleNamespace(base_path=None))
        assert found.resolve() == project.resolve()


class TestUiDetection:
    @pytest.mark.parametrize("fmt", ["toml", "json"])
    def test_detects_every_project_format(self, tmp_path, fmt):
        pytest.importorskip("fastapi")
        from ducta.console.ui import _detect_ducta_workspace

        root = tmp_path / f"p_{fmt}"
        rc = UnifiedCLI().run(
            ["init", "project", "--name", root.name, "--format", fmt, "--path", str(root)]
        )
        assert rc == 0
        with _cwd(root / "pipelines"):
            assert Path(_detect_ducta_workspace()).resolve() == root.resolve()

    def test_a_project_file_that_does_not_parse_is_still_opened(self, tmp_path):
        pytest.importorskip("fastapi")
        from ducta.console.ui import _detect_ducta_workspace

        (tmp_path / "ducta.yaml").write_text("version: 2\n  broken: [", encoding="utf-8")
        with _cwd(tmp_path):
            assert Path(_detect_ducta_workspace()).resolve() == tmp_path.resolve()


class TestCertify:
    def test_every_subcommand_takes_base_path(self):
        assert _parse(["certify", "list", "--base-path", "p"]).base_path == "p"
        assert _parse(["certify", "show", "--run-id", "x", "--base-path", "p"]).base_path == "p"
        assert _parse(["certify", "verify", "--run-id", "x", "--base-path", "p"]).base_path == "p"
        assert _parse(["certify", "diff", "a", "b", "--base-path", "p"]).base_path == "p"

    def test_declared_environments_are_searched(self, monkeypatch, project):
        from ducta.console.commands import certify_cmds
        from ducta.setting.environments import DEFAULT_ENVIRONMENTS

        declared = SimpleNamespace(project=SimpleNamespace(environments=["qa", "dev"]))
        monkeypatch.setattr(
            "ducta.setting.project_loader.validate_project", lambda root, *a, **k: declared
        )
        envs = certify_cmds._search_envs(SimpleNamespace(base_path=str(project)))
        assert envs == [*DEFAULT_ENVIRONMENTS, "qa"]

    def test_list_works_from_outside_the_project(self, project):
        with _cwd(project.parent):
            rc = UnifiedCLI().run(["certify", "list", "--base-path", project.name])
        assert rc == ExitCode.SUCCESS.value


class TestStreamStopTimeout:
    def test_the_timeout_reaches_the_engine(self, monkeypatch):
        from ducta.console import execution

        seen = {}

        class _Executor:
            def __init__(self, context):
                pass

            def stop_streaming_pipeline(self, execution_id, graceful=True, timeout_seconds=30.0):
                seen.update(graceful=graceful, timeout=timeout_seconds)
                return True

        monkeypatch.setattr(execution, "_load_streaming_context", lambda config, env: None)
        monkeypatch.setattr(execution, "PipelineExecutor", _Executor)
        assert execution.stop_streaming_pipeline_cli(None, "eid", timeout=120) == 0
        assert seen == {"graceful": True, "timeout": 120.0}


class TestSweepExitCode:
    def test_a_failed_trial_exits_like_a_failed_run(self):
        from ducta.console.commands.execution_cmds import ExecutionCommands

        rc = ExecutionCommands._report_sweep_result("s1", total=3, failures=1)
        assert rc == ExitCode.EXECUTION_ERROR.value


class TestAiApplyWithoutATerminal:
    def test_nothing_written_is_not_a_success(self, monkeypatch, tmp_path):
        from ducta.console.commands import ai_cmds

        monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))
        draft = SimpleNamespace(ok=True, files={"pipelines/x.yaml": "..."})
        written = []
        monkeypatch.setattr("ducta.ai.builder.apply_draft", lambda *a, **k: written.append(1))
        console = SimpleNamespace(print=lambda *a, **k: None)
        rc = ai_cmds.AICommands._write(
            console, tmp_path, draft, SimpleNamespace(yes=False, force=False)
        )
        assert rc == ExitCode.VALIDATION_ERROR.value
        assert written == []


class TestWrapperExtras:
    @pytest.mark.parametrize(
        "module, extra",
        [
            ("databricks", "databricks"),
            ("httpx", "ai"),
            ("ruamel", "ai"),
            ("fastapi", "api"),
            ("pyspark", "spark"),
        ],
    )
    def test_a_missing_module_names_its_extra(self, module, extra):
        from ducta.console.wrapper import _identify_feature_for_module

        assert _identify_feature_for_module(module) == extra
