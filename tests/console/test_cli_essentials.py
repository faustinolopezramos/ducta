"""``ducta list`` / ``ducta check`` and the grouped ``ducta start --help``.

The shortcuts must be the config commands, not copies of them; the regrouping of
``start``'s options must not lose or rename one.
"""

import argparse

import pytest

from ducta.console import cli
from ducta.console.parser import COMMAND_GROUPS, UnifiedArgumentParser

START_OPTIONS = {
    "--env", "--pipeline", "--node", "--mode", "--start-date", "--end-date", "--base-path",
    "--log-level", "--log-file", "--verbose", "--quiet", "--model-version", "--hyperparams",
    "--sweep", "--search", "--search-metric", "--search-trials", "--no-sweep-reuse",
    "--sweep-parallel", "--max-sweep-size", "--validate-only", "--dry-run", "--sanity-only",
    "--reuse-upstream", "--rerun-all",
}  # fmt: skip


def _start_parser() -> argparse.ArgumentParser:
    sub = next(
        a for a in UnifiedArgumentParser.create()._actions
        if isinstance(a, argparse._SubParsersAction)
    )  # fmt: skip
    return sub.choices["start"]


class TestShortcuts:
    def test_list_is_config_list_pipelines(self):
        short = UnifiedArgumentParser.create().parse_args(["list", "-e", "dev", "--filter", "ml"])
        long = UnifiedArgumentParser.create().parse_args(
            ["config", "list-pipelines", "--env", "dev", "--filter", "ml"]
        )
        assert short.config_command == "list-pipelines"
        for name in ("env", "filter_pattern", "output_format"):
            assert getattr(short, name) == getattr(long, name)

    def test_check_is_config_validate(self):
        short = UnifiedArgumentParser.create().parse_args(
            ["check", "-e", "dev", "-p", "etl", "--output-format", "json"]
        )
        long = UnifiedArgumentParser.create().parse_args(
            ["config", "validate", "--env", "dev", "--pipeline", "etl", "--output-format", "json"]
        )
        assert short.config_command == "validate"
        for name in ("env", "pipeline", "output_format"):
            assert getattr(short, name) == getattr(long, name)

    @pytest.mark.parametrize("command", ["list", "check"])
    def test_they_find_a_project_elsewhere(self, command):
        args = UnifiedArgumentParser.create().parse_args([command, "--base-path", "/p"])
        assert args.base_path == "/p"

    @pytest.mark.parametrize(
        "argv, expected",
        [(["list", "--filter", "x"], "list-pipelines"), (["check", "-e", "dev"], "validate")],
    )
    def test_they_run_the_config_handler(self, argv, expected, monkeypatch):
        seen = []
        monkeypatch.setattr(cli, "handle_config", lambda args: seen.append(args) or 0)
        assert cli.UnifiedCLI().run(argv) == 0
        assert [a.config_command for a in seen] == [expected]

    def test_they_are_in_the_essentials_group_first(self):
        group, commands = COMMAND_GROUPS[0]
        assert group == "Essentials"
        assert [name for name, _ in commands] == ["list", "check", "start", "stream"]
        text = UnifiedArgumentParser.create().format_help()
        assert text.index("Essentials:") < text.index("Get started:")
        assert "ducta list  ·  ducta check -e dev  ·  ducta start -e dev -p etl" in text


class TestStartHelp:
    def test_no_option_was_lost_or_renamed(self):
        longs = {
            s for a in _start_parser()._actions for s in a.option_strings if s.startswith("--")
        }
        assert longs - {"--help"} == START_OPTIONS

    def test_short_forms_and_defaults_are_unchanged(self):
        args = UnifiedArgumentParser.create().parse_args(
            ["start", "-e", "dev", "-p", "etl", "-n", "x"]
        )
        assert (args.env, args.pipeline, args.node) == ("dev", "etl", "x")
        defaults = UnifiedArgumentParser.create().parse_args(["start"])
        assert (defaults.env, defaults.mode, defaults.sweep_parallel, defaults.log_level) == (
            "base", "async", 1, "INFO",
        )  # fmt: skip
        assert UnifiedArgumentParser.create().parse_args(["start", "-m", "sync"]).mode == "sync"

    def test_the_options_are_grouped_by_how_often_they_are_needed(self):
        text = _start_parser().format_help()
        order = [
            text.index(title)
            for title in (
                "Common:",
                "Dates and re-runs:",
                "Streaming and hybrid pipelines:",
                "ML tuning (ML pipelines only):",
                "Logging:",
            )
        ]
        assert order == sorted(order)
        assert text.index("--dry-run") < text.index("Dates and re-runs:")
        assert text.index("--sweep-parallel") > text.index("ML tuning")
        assert text.startswith("usage: ducta start -e ENV -p PIPELINE [options]")

    def test_every_option_has_a_short_help(self):
        for action in _start_parser()._actions:
            assert action.help, action.option_strings
            assert len(action.help) <= 160, action.option_strings
