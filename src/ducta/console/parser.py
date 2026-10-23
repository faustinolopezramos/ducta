"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0
"""

import argparse
import difflib
import re
import sys
from typing import NoReturn

HELP_BASE_PATH = (
    "Project directory (default: the current directory or its nearest parent holding ducta.yaml)"
)
HELP_PIPELINE_NAME = "Pipeline name"
HELP_PIPELINE_NAME_TO_EXECUTE = "Pipeline name to execute"
HELP_CONFIG_FILE = (
    "ducta.yaml, or any file or directory inside the project "
    "(default: the project containing the current directory)"
)


_INVALID_CHOICE = re.compile(r"invalid choice: '([^']*)' \(choose from (.*)\)")


def _renamed_option(old: str, new: str):
    """An action for an option that was renamed: ``old`` still works and says so on stderr."""

    class _Renamed(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            if option_string == old:
                print(
                    f"warning: {old} is deprecated and will be removed; use {new}",
                    file=sys.stderr,
                )
            setattr(namespace, self.dest, values)

    return _Renamed


class _SuggestingParser(argparse.ArgumentParser):
    """``ArgumentParser`` that answers a mistyped subcommand with the one it is closest to.

    argparse's own message lists every choice, which for ``ducta`` is twelve names and
    leaves the reader to find the typo. Subparsers are created with their parent's class,
    so ``ducta config valdiate`` is covered too.
    """

    def error(self, message: str) -> NoReturn:
        commands = self._subcommands()
        if commands and message.startswith("the following arguments are required"):
            # `ducta config` alone said "required: config_command", a name
            # from the code. Say which commands there are instead.
            width = max(len(name) for name in commands) + 3
            lines = [f"{self.prog}: which command?", ""]
            lines += [f"  {name.ljust(width)}{text}" for name, text in commands.items()]
            lines += ["", f"Run `{self.prog} <command> --help` for its options."]
            self.exit(2, "\n".join(lines) + "\n")
        found = _INVALID_CHOICE.search(message)
        if found:
            typed = found.group(1)
            choices = re.findall(r"'([^']*)'", found.group(2))
            close = difflib.get_close_matches(typed, choices, n=1, cutoff=0.6)
            if close:
                message = f"unknown command '{typed}'. Did you mean '{close[0]}'?"
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")

    def _subcommands(self) -> "dict[str, str]":
        """This parser's subcommands and their one-line help, if it has any."""
        for action in self._actions:
            if isinstance(action, argparse._SubParsersAction):
                helps = {a.dest: a.help or "" for a in action._choices_actions}
                return {name: helps.get(name, "") for name in action.choices}
        return {}


#: ``ducta --help``: the commands by what they are for, each with one line.
#: The same line is the command's summary wherever argparse lists it.
COMMAND_GROUPS = (
    (
        "Essentials",
        (
            ("list", "Show the project's pipelines"),
            ("check", "Validate the project without running it"),
            ("start", "Run a batch, ML or hybrid pipeline"),
            ("stream", "Run, inspect and stop a streaming pipeline"),
        ),
    ),
    (
        "Get started",
        (
            ("init", "Create a project (init project) or a database connection"),
            ("template", "Create a project from a named template"),
        ),
    ),
    (
        "Inspect",
        (
            ("config", "Validate, list, show, explain, diff and convert the project"),
            ("certify", "List, show, verify and compare run certificates"),
            ("quality", "Run data quality checks and read their reports"),
            ("profile", "Propose the checks a data file already satisfies"),
        ),
    ),
    (
        "MLOps",
        (
            ("experiment", "List and compare tracked experiments and runs"),
            ("model", "Promote and clean up registered models"),
        ),
    ),
    (
        "AI",
        (
            ("ai", "Draft, fix, review and explain with a model"),
            ("skill", "Install Ducta's skill for AI assistants"),
        ),
    ),
    (
        "Web app",
        (
            ("ui", "Open the web app"),
            ("server", "Run the API server"),
        ),
    ),
)

#: The simplest thing each group does in ``ducta --help``: one command, or a tuple of
#: them (shown on one line). A test parses each one, so they cannot drift from the
#: real options.
GROUP_EXAMPLES = {
    "Essentials": ("ducta list", "ducta check -e dev", "ducta start -e dev -p etl"),
    "Get started": "ducta init project --name sales",
    "Inspect": "ducta config show -e dev",
    "MLOps": "ducta experiment list -e dev",
    "AI": 'ducta ai new "clean the orders and count them by day"',
    "Web app": "ducta ui",
}


def group_examples(group: str) -> "tuple[str, ...]":
    """The example commands of a help group, always as a tuple."""
    example = GROUP_EXAMPLES[group]
    return (example,) if isinstance(example, str) else tuple(example)


def example_line(group: str) -> str:
    """How a group's examples read in ``ducta --help``."""
    return "  ·  ".join(group_examples(group))


_GLOBAL_OPTIONS = (
    ("-h, --help", "Show this help"),
    ("-V, --version", "Show the version"),
    ("-v, --verbose", "Debug log lines too"),
    ("-q, --quiet", "Errors only"),
)


#: The short forms `start` has always had, given to every command with the option:
#: `ducta config validate -e dev` was "unrecognized arguments".
_SHORT_ALIASES = {"--env": "-e", "--pipeline": "-p"}


def _add_short_aliases(parser: argparse.ArgumentParser) -> None:
    """Add ``-e``/``-p`` wherever ``--env``/``--pipeline`` exist and the letter is free."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in set(action.choices.values()):
                _add_short_aliases(sub)
            continue
        for long, short in _SHORT_ALIASES.items():
            if long in action.option_strings and short not in parser._option_string_actions:
                action.option_strings = [short, *action.option_strings]
                parser._option_string_actions[short] = action


class _DuctaParser(_SuggestingParser):
    """The top-level parser: its help lists the commands by group."""

    def format_help(self) -> str:
        if self.prog != "ducta":
            return super().format_help()  # a subcommand's own help
        width = max(len(name) for _, cmds in COMMAND_GROUPS for name, _ in cmds) + 3
        lines = [
            "usage: ducta [-h] [-V] [-v] [-q] <command> [options]",
            "",
            "Ducta: data pipelines you can run, check and prove.",
        ]
        for group, commands in COMMAND_GROUPS:
            lines += ["", f"{group}:"]
            lines += [f"  {name.ljust(width)}{summary}" for name, summary in commands]
            if group in GROUP_EXAMPLES:
                lines.append(f"  {'e.g.'.ljust(width)}{example_line(group)}")
        opt_width = max(len(flag) for flag, _ in _GLOBAL_OPTIONS) + 3
        lines += ["", "Options:"]
        lines += [f"  {flag.ljust(opt_width)}{text}" for flag, text in _GLOBAL_OPTIONS]
        lines += [
            "",
            "Run `ducta <command> --help` for a command's options.",
            "Docs: https://ducta.readthedocs.io/",
            "",
        ]
        return "\n".join(lines)


class UnifiedArgumentParser:
    """Unified argument parser for all Ducta CLI commands."""

    @staticmethod
    def create() -> argparse.ArgumentParser:
        """Create configured argument parser with subcommands."""
        parser = _DuctaParser(
            prog="ducta",
            description="Ducta: data pipelines you can run, check and prove.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

        parser.add_argument("-V", "--version", action="store_true", help="Show the version")
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Debug log lines too",
        )
        parser.add_argument("-q", "--quiet", action="store_true", help="Errors only")

        subparsers = parser.add_subparsers(
            dest="subcommand", metavar="<command>", help="Command", required=False
        )

        UnifiedArgumentParser._add_list_subcommand(subparsers)
        UnifiedArgumentParser._add_check_subcommand(subparsers)
        UnifiedArgumentParser._add_start_subcommand(subparsers)
        UnifiedArgumentParser._add_stream_subcommand(subparsers)
        UnifiedArgumentParser._add_template_subcommand(subparsers)
        UnifiedArgumentParser._add_config_subcommand(subparsers)
        UnifiedArgumentParser._add_ui_subcommand(subparsers)
        UnifiedArgumentParser._add_server_subcommand(subparsers)
        UnifiedArgumentParser._add_quality_subcommand(subparsers)
        UnifiedArgumentParser._add_experiment_subcommand(subparsers)
        UnifiedArgumentParser._add_model_subcommand(subparsers)
        UnifiedArgumentParser._add_init_subcommand(subparsers)
        UnifiedArgumentParser._add_certify_subcommand(subparsers)
        UnifiedArgumentParser._add_ai_subcommand(subparsers)
        UnifiedArgumentParser._add_skill_subcommand(subparsers)

        summaries = {name: text for _, cmds in COMMAND_GROUPS for name, text in cmds}
        for action in subparsers._choices_actions:
            action.help = summaries.get(action.dest, action.help)
        _add_short_aliases(parser)

        return parser

    @staticmethod
    def _add_discovery_args(parser: argparse.ArgumentParser) -> None:
        """``--base-path``: where to look for the project (default: the current
        directory, then its parents)."""
        parser.add_argument("--base-path", help=HELP_BASE_PATH)

    @staticmethod
    def _add_list_args(parser: argparse.ArgumentParser) -> None:
        """Options of ``config list-pipelines`` and of its shortcut ``list``."""
        parser.add_argument("--env", help="Environment to use for listing")
        parser.add_argument(
            "--filter",
            dest="filter_pattern",
            default=None,
            help="Filter pipelines by name (case-insensitive substring match)",
        )
        parser.add_argument(
            "--output-format",
            "--format",
            dest="output_format",
            choices=["table", "json", "list"],
            default="table",
            action=_renamed_option("--format", "--output-format"),
            help="Output format: table (default), json, or list",
        )

    @staticmethod
    def _add_validate_args(parser: argparse.ArgumentParser) -> None:
        """Options of ``config validate`` and of its shortcut ``check``."""
        parser.add_argument(
            "--pipeline",
            default=None,
            help="Pipeline to validate (default: all pipelines)",
        )
        parser.add_argument("--env", help="Environment to use")
        UnifiedArgumentParser._add_output_format_arg(
            parser,
            "json: one JSON document on stdout — every problem with its file, line, node "
            "and suggested fix — for CI and AI assistants",
        )

    @staticmethod
    def _add_list_subcommand(subparsers):
        """``ducta list``: ``config list-pipelines``, one word shorter."""
        list_parser = subparsers.add_parser(
            "list",
            help="Show the project's pipelines",
            description="Show the project's pipelines (the same as `ducta config list-pipelines`).",
        )
        list_parser.set_defaults(config_command="list-pipelines")
        UnifiedArgumentParser._add_discovery_args(list_parser)
        UnifiedArgumentParser._add_list_args(list_parser)

    @staticmethod
    def _add_check_subcommand(subparsers):
        """``ducta check``: ``config validate``, one word shorter."""
        check_parser = subparsers.add_parser(
            "check",
            help="Validate the project without running it",
            description=(
                "Import node functions, check signatures, and resolve I/O keys without "
                "running Spark; reports every configuration error up front "
                "(the same as `ducta config validate`)."
            ),
        )
        check_parser.set_defaults(config_command="validate")
        UnifiedArgumentParser._add_discovery_args(check_parser)
        UnifiedArgumentParser._add_validate_args(check_parser)

    @staticmethod
    def _add_output_format_arg(parser: argparse.ArgumentParser, help_text: str) -> None:
        parser.add_argument(
            "--output-format", choices=["rich", "json"], default="rich", help=help_text
        )

    @staticmethod
    def _add_mlops_resolution_args(parser: argparse.ArgumentParser, pipeline_help: str) -> None:
        """``--storage-path``/``--env``/``--pipeline``: MLOps resolution group
        shared by ``experiment list``, ``model promote`` and ``model gc``.
        *pipeline_help* carries each subcommand's own full ``--pipeline`` help
        text, which differs in its closing clause."""
        parser.add_argument(
            "--storage-path",
            help="MLOps storage path (Optional, auto-discovered by default)",
            default=None,
        )
        parser.add_argument(
            "--env",
            help="Project environment to resolve the storage path from "
            "(e.g. dev, prod) — auto-discovery requires this",
            default=None,
        )
        parser.add_argument("--pipeline", help=pipeline_help, default=None)

    @staticmethod
    def _add_start_subcommand(subparsers):
        start_parser = subparsers.add_parser(
            "start",
            help="Start pipelines directly",
            description=(
                "Run a pipeline, and the pipelines it depends on, directly and "
                "without orchestration."
            ),
            usage="ducta start -e ENV -p PIPELINE [options]",
        )

        # Grouped by how often they are needed; every option keeps its name and meaning.
        common = start_parser.add_argument_group("Common")
        common.add_argument(
            "--env",
            "-e",
            default="base",
            help="Environment: base (default), dev, sandbox, prod or sandbox_<developer>",
        )
        common.add_argument("--pipeline", "-p", help="Pipeline to run (see: ducta list)")
        common.add_argument("--node", "-n", help="Run only this node")
        common.add_argument(
            "--dry-run", action="store_true", help="Show what would run, execute nothing"
        )
        common.add_argument(
            "--validate-only",
            action="store_true",
            help="Check the configuration, execute nothing",
        )
        common.add_argument(
            "--sanity-only",
            action="store_true",
            help="Check every node's inputs, execute nothing",
        )
        UnifiedArgumentParser._add_discovery_args(common)

        reruns = start_parser.add_argument_group("Dates and re-runs")
        reruns.add_argument("--start-date", help="First day to process (YYYY-MM-DD)")
        reruns.add_argument("--end-date", help="Last day to process (YYYY-MM-DD)")
        reruns.add_argument(
            "--reuse-upstream",
            action="store_true",
            help="In a depends_on chain, skip upstream pipelines whose outputs are "
            "already materialized (reads them from disk instead of recomputing)",
        )
        reruns.add_argument(
            "--rerun-all",
            action="store_true",
            help="Re-run the whole depends_on chain, ignoring chain reuse",
        )

        streaming = start_parser.add_argument_group("Streaming and hybrid pipelines")
        streaming.add_argument(
            "--mode",
            "-m",
            choices=["sync", "async"],
            default="async",
            help="Either way the command runs while the queries do: 'async' (default) "
            "reports their status and stops them on Ctrl+C; 'sync' waits inside the engine",
        )

        tuning = start_parser.add_argument_group(
            "ML tuning (ML pipelines only)",
            "How the search options combine is explained in the documentation: "
            "https://ducta.readthedocs.io/ (CLI usage, ML tuning).",
        )
        tuning.add_argument("--model-version", help="Model version")
        tuning.add_argument("--hyperparams", help="Hyperparameters as a JSON string")
        tuning.add_argument(
            "--sweep",
            help="Grid file (YAML/JSON): one run per combination, tagged with one sweep_id",
        )
        tuning.add_argument(
            "--search",
            action="store_true",
            help="Search with the strategy in the pipeline's hyperparams_config "
            "(grid, random or bayesian)",
        )
        tuning.add_argument(
            "--search-metric",
            help="Metric to optimize (default: hyperparams_config.objective.metric); "
            "use a validation metric, not a test one",
        )
        tuning.add_argument(
            "--search-trials",
            type=int,
            help="Trial budget for random and bayesian search (overrides n_trials)",
        )
        tuning.add_argument(
            "--no-sweep-reuse",
            action="store_true",
            help="Recompute every node on each trial instead of reusing upstream nodes",
        )
        tuning.add_argument(
            "--sweep-parallel",
            type=int,
            default=1,
            metavar="N",
            help="Run N trials at once, each in its own process",
        )
        tuning.add_argument(
            "--max-sweep-size",
            type=int,
            default=None,
            metavar="N",
            help="Largest grid a --sweep or --search may expand to (default: 50)",
        )

        logging_group = start_parser.add_argument_group("Logging")
        logging_group.add_argument(
            "--log-level",
            default="INFO",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            help="Logging level",
        )
        logging_group.add_argument("--log-file", help="Custom log file path")
        # Also accepted before the command (`ducta -v start …`). SUPPRESS keeps an
        # absent flag here from overwriting one given there.
        logging_group.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Debug log lines too",
        )
        logging_group.add_argument(
            "-q",
            "--quiet",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Errors only",
        )

    @staticmethod
    def _add_stream_subcommand(subparsers):
        stream_parser = subparsers.add_parser(
            "stream",
            help="Manage streaming pipelines",
            description="Manage real-time streaming pipelines",
        )
        stream_subparsers = stream_parser.add_subparsers(
            dest="stream_command", help="Streaming commands", required=True
        )

        run_parser = stream_subparsers.add_parser("run", help="Run streaming pipeline")
        run_parser.add_argument("--config", "-c", help=HELP_CONFIG_FILE)
        run_parser.add_argument("--pipeline", "-p", required=True, help="Pipeline name to execute")
        run_parser.add_argument(
            "--env",
            "-e",
            default="base",
            help="Execution environment (base, dev, prod, …)",
        )
        run_parser.add_argument(
            "--mode",
            "-m",
            default="async",
            choices=["sync", "async"],
            help="Either way the command runs while the queries do (they live in its "
            "process): 'async' (default) reports their status and stops them on Ctrl+C; "
            "'sync' waits inside the engine",
        )
        run_parser.add_argument("--model-version", help="Model version for ML pipelines")
        run_parser.add_argument("--hyperparams", help="Hyperparameters as JSON string")
        run_parser.add_argument(
            "--transforms-module",
            nargs="*",
            default=[],
            metavar="MODULE",
            dest="transforms_module",
            help="Python module path(s) to import before starting the pipeline. Each module must expose a register_transforms(registry) function. Example: src.streaming_fraud_realtime",
        )

        plan_parser = stream_subparsers.add_parser(
            "plan",
            help="Show what a streaming pipeline would do, without starting it",
            description="Resolve a streaming pipeline and print, per node, what it reads, "
            "what it writes, how often it fires and where its checkpoint will be, and what "
            "would stop it: a transform that is not registered, a source path that does not "
            "exist, two nodes sharing a checkpoint, an invalid node. Starts no Spark; exits "
            "non-zero when there are errors.",
        )
        plan_parser.add_argument("--config", "-c", help=HELP_CONFIG_FILE)
        plan_parser.add_argument("--pipeline", "-p", required=True, help="Pipeline name to plan")
        plan_parser.add_argument(
            "--env", "-e", default="base", help="Execution environment (base, dev, prod, …)"
        )
        plan_parser.add_argument(
            "--transforms-module",
            nargs="*",
            default=[],
            metavar="MODULE",
            dest="transforms_module",
            help="Python module path(s) to import before checking transforms, as for `stream run`",
        )
        plan_parser.add_argument(
            "--output-format",
            dest="output_format",
            default="table",
            choices=["table", "json"],
            help="Output format",
        )

        status_parser = stream_subparsers.add_parser(
            "status", help="Check streaming pipeline status"
        )
        status_parser.add_argument("--config", "-c", help=HELP_CONFIG_FILE)
        status_parser.add_argument("--env", "-e", default="base", help="Execution environment")
        status_parser.add_argument("--execution-id", "-i", help="Specific execution ID to check")
        status_parser.add_argument(
            "--output-format",
            "--format",
            "-f",
            dest="format",
            default="table",
            choices=["table", "json"],
            action=_renamed_option("--format", "--output-format"),
            help="Output format",
        )

        stop_parser = stream_subparsers.add_parser("stop", help="Stop streaming pipeline")
        stop_parser.add_argument("--config", "-c", help=HELP_CONFIG_FILE)
        stop_parser.add_argument("--env", "-e", default="base", help="Execution environment")
        stop_parser.add_argument("--execution-id", "-i", required=True, help="Execution ID to stop")
        stop_parser.add_argument(
            "--timeout",
            "-t",
            type=int,
            default=60,
            help="Seconds to wait for each query to stop gracefully (default: 60); "
            "under 5 stops them at once",
        )

    @staticmethod
    def _add_template_subcommand(subparsers):
        template_parser = subparsers.add_parser(
            "template",
            help="Generate project templates",
            description="Generate Ducta project templates and boilerplate code",
        )
        template_parser.add_argument("--template", help="Template type to generate")
        template_parser.add_argument("--project-name", help="Project name for template")
        template_parser.add_argument("--output-path", help="Output path for generated files")
        template_parser.add_argument(
            "--sandbox-developers",
            nargs="*",
            help="List of developer names for sandbox environments",
        )
        template_parser.add_argument(
            "--format",
            dest="config_format",
            choices=["yaml", "toml", "json"],
            default="yaml",
            help=(
                "Format of ducta, catalog and pipeline files (default: yaml, which keeps "
                "the explanatory comments; toml and json are the same project without them)"
            ),
        )
        template_parser.add_argument(
            "--no-sample-code",
            action="store_true",
            help="Do not include sample code in generated template",
        )
        template_parser.add_argument(
            "--list-templates", action="store_true", help="List available templates"
        )
        template_parser.add_argument(
            "--evidence-level",
            choices=["off", "record", "required", "signed"],
            default="record",
            help=(
                "How much evidence each run must leave (written to global_config): "
                "off = no certificate; record = certificate, a write failure only warns "
                "(default); required = a run without its certificate fails; signed = "
                "required + HMAC signature, preflight fails without DUCTA_CERTIFICATE_KEY"
            ),
        )

    @staticmethod
    def _add_config_subcommand(subparsers):
        config_parser = subparsers.add_parser(
            "config",
            help="Manage configuration",
            description="Manage Ducta configuration and discovery",
        )
        config_subparsers = config_parser.add_subparsers(
            dest="config_command", help="Configuration commands", required=True
        )

        list_pipelines_parser = config_subparsers.add_parser(
            "list-pipelines", help="List available pipelines"
        )
        UnifiedArgumentParser._add_list_args(list_pipelines_parser)

        pipeline_info_parser = config_subparsers.add_parser(
            "pipeline-info", help="Show pipeline information"
        )
        pipeline_info_parser.add_argument("--pipeline", required=True, help=HELP_PIPELINE_NAME)
        pipeline_info_parser.add_argument("--env", help="Environment to use")

        validate_parser = config_subparsers.add_parser(
            "validate",
            help="Preflight-validate pipeline config before executing",
            description=(
                "Import node functions, check signatures, and resolve I/O keys without "
                "running Spark. Reports every configuration error up front."
            ),
        )
        UnifiedArgumentParser._add_validate_args(validate_parser)

        show_parser = config_subparsers.add_parser(
            "show",
            help="Print the project as it resolves for an environment",
            description=(
                "The project after templates (extends), defaults and the environment's "
                "overrides are applied: what Ducta actually runs. Use --format to read it "
                "as YAML, TOML or JSON."
            ),
        )
        show_parser.add_argument("--env", help="Environment to resolve (default: the base project)")
        show_parser.add_argument(
            "--pipeline", default=None, help="Only this pipeline and the datasets it touches"
        )
        show_parser.add_argument(
            "--format",
            dest="output_format",
            choices=["yaml", "toml", "json"],
            default="yaml",
            help="Output format (default: yaml)",
        )
        show_parser.add_argument(
            "--engine",
            action="store_true",
            help="Print the five documents the engine reads instead of the project's shape",
        )
        show_parser.add_argument(
            "--ml",
            action="store_true",
            help=(
                "What each ML node will be given: its split and where it was declared, "
                "whether it must apply it, its merged hyperparameters and model version"
            ),
        )

        explain_parser = config_subparsers.add_parser(
            "explain",
            help="Say where one setting's value comes from",
            description=(
                "Follows a value through the file, the pipeline template, defaults and the "
                "environment's overrides, with the file and line of each step."
            ),
        )
        explain_parser.add_argument(
            "path",
            help="e.g. settings.max_parallel_nodes or pipelines.etl.nodes.load.retry",
        )
        explain_parser.add_argument("--env", help="Environment to resolve (default: base)")

        diff_parser = config_subparsers.add_parser(
            "diff", help="Show what differs between two environments"
        )
        diff_parser.add_argument("env_a", help="First environment (use 'base' for none)")
        diff_parser.add_argument("env_b", help="Second environment")

        convert_parser = config_subparsers.add_parser(
            "convert",
            help="Write the project's configuration files in another format",
            description=(
                "Rewrites ducta, catalog, pipelines/ and templates/ as YAML, TOML or JSON "
                "in a new directory. Comments are not carried over; your Python and data "
                "are not copied."
            ),
        )
        convert_parser.add_argument(
            "--to", dest="to_format", choices=["yaml", "toml", "json"], required=True
        )
        convert_parser.add_argument("--out", required=True, help="New directory to write into")

        schema_parser = config_subparsers.add_parser(
            "schema", help="Print (or write) the JSON Schema of the format-2 configuration files"
        )
        schema_parser.add_argument(
            "--out", default=None, help="Directory to write project/catalog/pipeline.json into"
        )

        UnifiedArgumentParser._add_discovery_args(config_parser)
        # Also after the subcommand (`ducta config validate --base-path p`), as
        # every other command takes it. SUPPRESS keeps the subcommand's absent
        # option from overwriting a value given before it.
        for name, sub in config_subparsers.choices.items():
            if name != "schema":
                sub.add_argument("--base-path", help=HELP_BASE_PATH, default=argparse.SUPPRESS)

    @staticmethod
    def _add_ui_subcommand(subparsers):
        ui_parser = subparsers.add_parser(
            "ui",
            help="Launch the visual interface",
            description="Launch the Ducta React frontend and FastAPI backend",
        )
        ui_parser.add_argument(
            "--port", type=int, default=8000, help="Port to run the UI server on (default: 8000)"
        )
        ui_parser.add_argument(
            "--host", default="127.0.0.1", help="Host to bind the UI server to (default: 127.0.0.1)"
        )
        ui_parser.add_argument(
            "--no-browser", action="store_true", help="Do not automatically open the browser"
        )
        ui_parser.add_argument(
            "--source", help="Workspace source path or Git URL to load automatically"
        )
        ui_parser.add_argument(
            "--db",
            dest="db_path",
            default=None,
            help="Path for the SQLite execution history database (default: ~/.ducta/executions.db)",
        )
        ui_parser.add_argument(
            "--enable-terminal",
            action="store_true",
            help="Enable the embedded web terminal (PTY). SECURITY: grants arbitrary shell execution to authenticated users. Off by default.",
        )

    @staticmethod
    def _add_server_subcommand(subparsers):
        server_parser = subparsers.add_parser(
            "server",
            help="Manage the local Ducta server",
            description="Start the local Ducta server with the web dashboard and API",
        )
        server_subparsers = server_parser.add_subparsers(
            dest="server_command", help="Server commands", required=True
        )

        start_parser = server_subparsers.add_parser(
            "start",
            help="Start the local Ducta server",
            description="Start the local Ducta server with the MLflow-style web dashboard",
        )
        start_parser.add_argument(
            "--port", type=int, default=8000, help="Port to run the server on (default: 8000)"
        )
        start_parser.add_argument(
            "--host", default="127.0.0.1", help="Host to bind the server to (default: 127.0.0.1)"
        )
        start_parser.add_argument(
            "--no-browser", action="store_true", help="Do not automatically open the browser"
        )
        start_parser.add_argument(
            "--source", help="Workspace source path or Git URL to load automatically"
        )
        start_parser.add_argument(
            "--db",
            dest="db_path",
            default=None,
            help="Path for the SQLite execution history database (default: ~/.ducta/executions.db)",
        )

    @staticmethod
    def _add_quality_subcommand(subparsers):
        profile_parser = subparsers.add_parser(
            "profile",
            help="Assay a dataset and propose the quality spec it already satisfies",
            description=(
                "Measure a dataset and emit a reviewable spec derived from what is "
                "actually in it, instead of requiring the thresholds to be known in "
                "advance. Runs standalone on a file: no project, no DAG, no Spark."
            ),
        )
        profile_parser.add_argument("--input", "-i", required=True, help="Path to the data file")
        profile_parser.add_argument(
            "--format",
            "-f",
            default="parquet",
            choices=["parquet", "csv", "json"],
            help="Input file format (default: parquet)",
        )
        profile_parser.add_argument(
            "--output",
            "-o",
            help="Write the proposed spec here (default: print it to stdout)",
        )
        profile_parser.add_argument(
            "--strictness",
            default="balanced",
            choices=["strict", "balanced", "lax"],
            help="How close the proposed bounds sit to what was observed (default: balanced)",
        )
        profile_parser.add_argument(
            "--sample-rows",
            type=int,
            help="Measure columns from a sample of at most N rows (row count stays exact)",
        )
        profile_parser.add_argument(
            "--dataset-name",
            help="Name for the dataset in the spec (default: the file stem)",
        )
        UnifiedArgumentParser._add_output_format_arg(
            profile_parser, help_text="How to render the profile (default: rich)"
        )

        quality_parser = subparsers.add_parser(
            "quality",
            help="Manage data quality checks",
            description="Run, inspect, and validate Ducta data quality checks",
        )
        quality_subparsers = quality_parser.add_subparsers(
            dest="quality_command", help="Quality commands", required=True
        )

        quality_subparsers.add_parser(
            "list", help="List all registered quality checks (built-in and custom)"
        )

        run_qp = quality_subparsers.add_parser(
            "run", help="Run quality checks standalone on a data file"
        )
        run_qp.add_argument("--input", "-i", required=True, help="Path to input data file")
        run_qp.add_argument(
            "--format",
            "-f",
            default="parquet",
            choices=["parquet", "csv", "json"],
            help="Input file format (default: parquet)",
        )
        run_qp.add_argument(
            "--config",
            "-c",
            required=True,
            help="Path to a TOML/YAML file with check config (checks table)",
        )
        run_qp.add_argument("--fail-fast", action="store_true", help="Stop on first failing check")
        UnifiedArgumentParser._add_output_format_arg(
            run_qp, help_text="Report output format (default: rich)"
        )

        report_qp = quality_subparsers.add_parser(
            "report", help="Show stored quality reports for a dataset"
        )
        report_qp.add_argument(
            "--dataset", "-d", required=True, help="Dataset name whose reports to display"
        )
        report_qp.add_argument(
            "--workspace",
            "-w",
            default=".",
            help="Workspace root path (default: current directory)",
        )
        report_qp.add_argument(
            "--run-id", "-r", help="Specific run ID to display (default: latest)"
        )
        report_qp.add_argument(
            "--all",
            dest="all_reports",
            action="store_true",
            help="List all stored run IDs for the dataset",
        )
        UnifiedArgumentParser._add_output_format_arg(
            report_qp, help_text="Report output format (default: rich)"
        )
        report_qp.add_argument(
            "--env",
            "-e",
            help="Environment to resolve the project's real quality.output "
            "storage from (base, dev, sandbox, prod, ...), instead of the "
            "standalone --workspace/.quality convention used by "
            "'ducta quality run'. Reads reports a real pipeline run persisted.",
        )
        report_qp.add_argument(
            "--pipeline",
            "-p",
            help="Pipeline name the report was recorded under (as named in "
            "config/pipelines, e.g. 'golden.transformation'). A report saved "
            "by a real pipeline run is scoped under its pipeline name, not "
            "the standalone default — omitting this when --env is a real "
            "project looks in the wrong place and reports no reports found.",
        )
        report_qp.add_argument("--base-path", help=HELP_BASE_PATH)

        trend_qp = quality_subparsers.add_parser(
            "trend", help="Show score time-series for a dataset"
        )
        trend_qp.add_argument("--dataset", "-d", required=True, help="Dataset name")
        trend_qp.add_argument(
            "--workspace", "-w", default=".", help="Workspace root path (default: .)"
        )
        trend_qp.add_argument(
            "--last",
            "-n",
            type=int,
            default=20,
            dest="last_n",
            help="Number of recent scores to show (default: 20)",
        )
        UnifiedArgumentParser._add_output_format_arg(
            trend_qp, help_text="Output format (default: rich)"
        )
        trend_qp.add_argument(
            "--env",
            "-e",
            help="Environment to resolve the project's real quality.output "
            "storage from, instead of the standalone --workspace convention.",
        )
        trend_qp.add_argument(
            "--pipeline",
            "-p",
            help="Pipeline name the score history was recorded under (see "
            "'ducta quality report --help'). Omitting this when --env is a "
            "real project looks in the wrong place and reports no history.",
        )
        trend_qp.add_argument("--base-path", help=HELP_BASE_PATH)

        score_qp = quality_subparsers.add_parser(
            "score", help="Show composite pipeline quality score for a run"
        )
        score_qp.add_argument(
            "--run-id", "-r", required=True, dest="run_id", help="Pipeline run ID"
        )
        score_qp.add_argument(
            "--workspace", "-w", default=".", help="Workspace root path (default: .)"
        )
        UnifiedArgumentParser._add_output_format_arg(
            score_qp, help_text="Output format (default: rich)"
        )
        score_qp.add_argument(
            "--env",
            "-e",
            help="Environment to resolve the project's real quality.output "
            "storage from, instead of the standalone --workspace convention.",
        )
        score_qp.add_argument("--base-path", help=HELP_BASE_PATH)

        validate_qp = quality_subparsers.add_parser(
            "validate-config", help="Validate quality config for a node without executing"
        )
        validate_qp.add_argument(
            "--node", "-n", required=True, help="Node name whose quality config to validate"
        )
        validate_qp.add_argument(
            "--env", "-e", default="base", help="Environment whose configuration to check"
        )
        validate_qp.add_argument("--base-path", help=HELP_BASE_PATH)

    @staticmethod
    def _add_experiment_subcommand(subparsers):
        exp_parser = subparsers.add_parser(
            "experiment",
            help="Manage MLOps experiments",
            description="List, inspect and compare MLOps experiment tracking data",
        )
        exp_sub = exp_parser.add_subparsers(
            dest="experiment_command", help="Experiment commands", required=True
        )
        list_p = exp_sub.add_parser("list", help="List recent experiments")
        UnifiedArgumentParser._add_mlops_resolution_args(
            list_p,
            pipeline_help="Pipeline name (schema.pipeline) to resolve a per-pipeline "
            "storage path — matches how a real run resolves its own path when "
            "no global 'mlops_path' override is set. Omit to look at the "
            "environment's shared/default MLOps directory instead.",
        )
        list_p.add_argument(
            "--limit",
            type=int,
            help="Maximum number of experiments to show (default: all)",
            default=None,
        )

        pipeline_help = (
            "Pipeline name (schema.pipeline) to resolve a per-pipeline storage path — "
            "matches how a real run resolves its own path when no global 'mlops_path' "
            "override is set."
        )
        runs_p = exp_sub.add_parser("runs", help="List the runs of one experiment")
        runs_p.add_argument("experiment_id", help="Experiment id (see `experiment list`)")
        UnifiedArgumentParser._add_mlops_resolution_args(runs_p, pipeline_help=pipeline_help)
        runs_p.add_argument(
            "--status",
            choices=["running", "completed", "failed", "scheduled"],
            help="Only runs in this status",
            default=None,
        )
        runs_p.add_argument(
            "--limit", type=int, help="Maximum number of runs (newest first)", default=None
        )
        UnifiedArgumentParser._add_output_format_arg(
            runs_p, "Output format: a text table or JSON (default: rich)"
        )

        show_p = exp_sub.add_parser("show", help="Show one run: parameters, metrics, artifacts")
        show_p.add_argument("run_id", help="Run id, or a unique prefix of it")
        UnifiedArgumentParser._add_mlops_resolution_args(show_p, pipeline_help=pipeline_help)
        UnifiedArgumentParser._add_output_format_arg(
            show_p, "Output format: text or JSON (default: rich)"
        )

        cmp_p = exp_sub.add_parser("compare", help="Compare the parameters and metrics of runs")
        cmp_p.add_argument("run_ids", nargs="+", help="Two or more run ids (or unique prefixes)")
        UnifiedArgumentParser._add_mlops_resolution_args(cmp_p, pipeline_help=pipeline_help)
        UnifiedArgumentParser._add_output_format_arg(
            cmp_p, "Output format: a text table or JSON (default: rich)"
        )

    @staticmethod
    def _add_model_subcommand(subparsers):
        mod_parser = subparsers.add_parser(
            "model",
            help="Manage MLOps model registry",
            description="Promote, garbage collect, and manage registered models",
        )
        mod_sub = mod_parser.add_subparsers(
            dest="model_command", help="Model commands", required=True
        )

        prom_p = mod_sub.add_parser("promote", help="Promote a model version to a new stage")
        prom_p.add_argument("name", help="Model name")
        prom_p.add_argument(
            "version", help="Model version: the whole number the registry assigned (3 or v3)"
        )
        prom_p.add_argument(
            "stage", choices=["staging", "production", "archived"], help="Target stage"
        )
        UnifiedArgumentParser._add_mlops_resolution_args(
            prom_p,
            pipeline_help="Pipeline name (schema.pipeline) to resolve a per-pipeline "
            "storage path — matches how a real run resolves its own path when "
            "no global 'mlops_path' override is set.",
        )
        prom_p.add_argument(
            "--force",
            action="store_true",
            help="Bypass the promotion policy gate (the bypass is audit-logged)",
        )

        gc_p = mod_sub.add_parser("gc", help="Garbage collect old model versions")
        gc_p.add_argument(
            "--dry-run", action="store_true", help="Show what would be deleted without deleting"
        )
        UnifiedArgumentParser._add_mlops_resolution_args(
            gc_p,
            pipeline_help="Pipeline name (schema.pipeline) to resolve a per-pipeline "
            "storage path — matches how a real run resolves its own path when "
            "no global 'mlops_path' override is set. Omit to garbage-collect "
            "the environment's shared/default MLOps directory instead.",
        )

    @staticmethod
    def _add_init_subcommand(subparsers):
        init_parser = subparsers.add_parser(
            "init",
            help="Initialize pipeline components",
            description="Initialize Ducta pipeline components (ingestion, etc.)",
        )
        init_subparsers = init_parser.add_subparsers(
            dest="init_command", help="Init commands", required=True
        )

        project_parser = init_subparsers.add_parser(
            "project",
            help="Create a project with the recommended layout",
            description=(
                "Create a new Ducta project: ducta.<ext>, catalog/<layer>.<ext>, "
                "quality/profiles.<ext>, pipelines/<layer>.<domain>.<ext>, the Python the "
                "nodes run, and the editor schemas. `ducta template` writes the same "
                "projects with every dataset in one catalog file (--layout single here)."
            ),
        )
        project_parser.add_argument("--name", required=True, help="Project name")
        project_parser.add_argument(
            "--type",
            dest="project_type",
            choices=["batch", "ml", "streaming", "hybrid"],
            default="batch",
            help="What the project does (default: batch, a bronze/silver/gold ETL)",
        )
        project_parser.add_argument(
            "--format",
            dest="config_format",
            choices=["yaml", "toml", "json"],
            default="yaml",
            help="Format of the configuration files (default: yaml, which keeps the comments)",
        )
        project_parser.add_argument(
            "--path", help="Directory to create (default: ./<name>; it must be empty or new)"
        )
        project_parser.add_argument(
            "--layout",
            choices=["split", "single"],
            default="split",
            help="split: catalog/ by layer + quality/profiles (default); single: one catalog file",
        )

        ing_parser = init_subparsers.add_parser(
            "ingestion",
            help="Manage database connections",
            description="Simple database connection management for Ducta ingestion",
        )
        ing_subparsers = ing_parser.add_subparsers(
            dest="ingestion_command", help="Ingestion commands", required=True
        )

        # Setup command
        ing_subparsers.add_parser(
            "setup",
            help="Setup a new database connection (interactive)",
            description="Interactive wizard to configure a new database connection",
        )

        # List command
        ing_subparsers.add_parser(
            "list",
            help="List all configured database connections",
        )

        # Test command
        test_parser = ing_subparsers.add_parser(
            "test",
            help="Test a database connection",
        )
        test_parser.add_argument("--source", required=True, help="Connection name to test")

        # Info command
        info_parser = ing_subparsers.add_parser(
            "info",
            help="Show connection details",
        )
        info_parser.add_argument("--source", required=True, help="Connection name to show")

    @staticmethod
    def _add_certify_subcommand(subparsers):
        certify_parser = subparsers.add_parser(
            "certify",
            help="Inspect and verify Run Certificates",
            description=(
                "Every terminating run writes a tamper-evident Run Certificate "
                "(${output_path}/${environment}/.ducta/runs/<run_id>/certificate.json "
                "by default). List, show, or verify them."
            ),
        )
        certify_subparsers = certify_parser.add_subparsers(
            dest="certify_command", help="Certificate commands", required=True
        )

        list_parser = certify_subparsers.add_parser("list", help="List run certificates")
        list_parser.add_argument(
            "--dir", help="Runs directory (default: resolved per environment from config)"
        )
        list_parser.add_argument(
            "--env", help="Environment to scope the search to (default: search all environments)"
        )

        show_parser = certify_subparsers.add_parser(
            "show", help="Show a certificate (human-readable by default)"
        )
        show_parser.add_argument("--run-id", required=True, help="Run id (or a unique prefix)")
        show_parser.add_argument(
            "--dir", help="Runs directory (default: resolved per environment from config)"
        )
        show_parser.add_argument(
            "--env", help="Environment to scope the search to (default: search all environments)"
        )
        show_parser.add_argument(
            "--json", action="store_true", help="Print the full certificate as raw JSON"
        )

        verify_parser = certify_subparsers.add_parser(
            "verify",
            help="Verify a certificate (tamper check, optionally re-run to prove reproducibility)",
        )
        verify_parser.add_argument("--run-id", required=True, help="Run id (or a unique prefix)")
        verify_parser.add_argument(
            "--dir", help="Runs directory (default: resolved per environment from config)"
        )
        verify_parser.add_argument(
            "--env", help="Environment to scope the search to (default: search all environments)"
        )
        verify_parser.add_argument(
            "--reproduce",
            action="store_true",
            help="Re-run the pipeline and confirm every output reproduces the certificate",
        )
        verify_parser.add_argument("--start-date", help="Start date for the reproduction run")
        verify_parser.add_argument("--end-date", help="End date for the reproduction run")

        diff_parser = certify_subparsers.add_parser(
            "diff", help="Compare two run certificates (config, outputs, quality)"
        )
        diff_parser.add_argument("run_a", help="First run id (or a unique prefix)")
        diff_parser.add_argument("run_b", help="Second run id (or a unique prefix)")
        diff_parser.add_argument(
            "--dir", help="Runs directory (default: resolved per environment from config)"
        )
        diff_parser.add_argument(
            "--env", help="Environment to scope the search to (default: search all environments)"
        )
        # Like every command that works on a project: from outside it, name it.
        for sub in (list_parser, show_parser, verify_parser, diff_parser):
            UnifiedArgumentParser._add_discovery_args(sub)

    @staticmethod
    def _add_skill_subcommand(subparsers):
        from ducta.console.commands.skill_cmds import DEFAULT_TARGETS, TARGETS

        skill_parser = subparsers.add_parser(
            "skill",
            help="Install Ducta's skill for AI assistants (Claude Code, Codex, Gemini, Copilot…)",
            description=(
                "Ducta ships an agent skill in the open Agent Skills format (agentskills.io): "
                "instructions, references and checks that let an AI assistant install, "
                "configure, run and debug Ducta with you. Install it where your assistant "
                "looks for skills."
            ),
        )
        skill_sub = skill_parser.add_subparsers(
            dest="skill_command", help="Skill commands", required=True
        )
        install = skill_sub.add_parser(
            "install",
            help="Copy the skill into this project (or your home) for one or more assistants",
        )
        install.add_argument(
            "--target",
            action="append",
            choices=list(TARGETS),
            help=(
                "Assistant to install for; repeat for several. "
                + "; ".join(f"{k}: {t.label} ({t.project})" for k, t in TARGETS.items())
                + f". Default: {' and '.join(DEFAULT_TARGETS)}"
            ),
        )
        install.add_argument(
            "--global",
            dest="user",
            action="store_true",
            help="Install in your home directory, for every project, instead of this project",
        )
        install.add_argument("--path", help="Install into this skills folder instead")
        install.add_argument(
            "--force", action="store_true", help="Replace an installed skill of another version"
        )
        install.add_argument(
            "--agents",
            action="store_true",
            help="Also install Ducta's agents (ducta-architect, ducta-sentinel) as Claude Code "
            "agent definitions in .claude/agents/",
        )
        install.add_argument(
            "--agents-md",
            action="store_true",
            help="Also add a short Ducta section to the project's AGENTS.md, read by "
            "assistants without skill support",
        )
        export = skill_sub.add_parser(
            "export", help="Write the skill as a zip (for claude.ai, the Skills API, others)"
        )
        export.add_argument("--zip", default="ducta-skill.zip", help="Zip file to write")
        skill_sub.add_parser("path", help="Print where the packaged skill is")

    @staticmethod
    def _add_ai_subcommand(subparsers):
        ai_parser = subparsers.add_parser(
            "ai",
            help="Draft pipelines with an AI model, local or behind an API key",
            description=(
                "Choose a model (local: Ollama, LM Studio, any OpenAI-compatible server; "
                "remote: Anthropic, OpenAI) and draft pipelines with it. A draft is "
                "validated like an unsaved edit in the UI and written only when you "
                "accept it; nothing is run or committed. Settings live in ~/.ducta/ai.toml."
            ),
        )
        ai_sub = ai_parser.add_subparsers(dest="ai_command", help="AI commands", required=True)

        from ducta.ai.config import EFFORTS, PRESETS

        setup = ai_sub.add_parser("setup", help="Choose the provider and model")
        setup.add_argument("--provider", required=True, choices=list(PRESETS))
        setup.add_argument(
            "--model", help="Model name (default: the largest code model a local server serves)"
        )
        setup.add_argument("--base-url", help="Endpoint, e.g. http://localhost:8000/v1")
        setup.add_argument(
            "--api-key-env", help="Name of the variable holding the key (never the key itself)"
        )
        setup.add_argument("--effort", choices=list(EFFORTS), help="Anthropic: reasoning effort")

        login = ai_sub.add_parser("login", help="Keep an API key in the system keychain")
        login.add_argument("--provider", choices=list(PRESETS), help="Default: the configured one")
        logout = ai_sub.add_parser("logout", help="Remove the API key from the keychain")
        logout.add_argument("--provider", choices=list(PRESETS), help="Default: the configured one")

        ai_sub.add_parser("doctor", help="Show the configuration and check the model answers")

        new = ai_sub.add_parser("new", help="Draft a new pipeline from a description")
        new.add_argument("request", help='What to build, e.g. "silver pipeline that cleans orders"')
        UnifiedArgumentParser._add_discovery_args(new)
        new.add_argument(
            "--attempts", type=int, help="Times the model may fix validation problems (default 3)"
        )
        new.add_argument("--write", action="store_true", help="Write the draft once it validates")
        new.add_argument("--yes", action="store_true", help="Do not ask before writing")
        new.add_argument("--force", action="store_true", help="Write even if it does not validate")
        UnifiedArgumentParser._add_output_format_arg(new, "Output format (json prints the draft)")

        fix = ai_sub.add_parser(
            "fix",
            help="Draft a fix for a pipeline: its validation problems, a run's error, or a note",
        )
        fix.add_argument("pipeline", help="Pipeline to fix")
        fix.add_argument(
            "--note", help='What is wrong, in your words (e.g. "amounts come in cents")'
        )
        fix.add_argument(
            "--error-file", help="File holding the error or traceback a run failed with"
        )
        UnifiedArgumentParser._add_discovery_args(fix)
        fix.add_argument(
            "--attempts", type=int, help="Times the model may fix validation problems (default 3)"
        )
        fix.add_argument("--write", action="store_true", help="Write the draft once it validates")
        fix.add_argument("--yes", action="store_true", help="Do not ask before writing")
        fix.add_argument("--force", action="store_true", help="Write even if it does not validate")
        UnifiedArgumentParser._add_output_format_arg(fix, "Output format (json prints the draft)")

        extend_p = ai_sub.add_parser(
            "extend",
            help="Draft new nodes for an existing pipeline (existing nodes stay as they are)",
            description=(
                "The model reads the pipeline's file and the code its nodes run, and adds what "
                "you describe: new nodes, functions and datasets. Ducta checks — without a model "
                "— that every existing node, function and setting is unchanged; the draft is "
                "reviewed and applied like any other."
            ),
        )
        extend_p.add_argument("pipeline", help="Pipeline to add nodes to")
        extend_p.add_argument("request", help="What the new nodes should do")
        UnifiedArgumentParser._add_discovery_args(extend_p)
        extend_p.add_argument(
            "--attempts", type=int, help="Times the model may fix what is found (default 3)"
        )
        extend_p.add_argument(
            "--write", action="store_true", help="Write the draft once it validates"
        )
        extend_p.add_argument("--yes", action="store_true", help="Do not ask before writing")
        extend_p.add_argument(
            "--force", action="store_true", help="Write even if it does not validate"
        )
        UnifiedArgumentParser._add_output_format_arg(
            extend_p, "Output format (json prints the draft)"
        )

        def draft_args(p, what: str = "the draft") -> None:
            UnifiedArgumentParser._add_discovery_args(p)
            p.add_argument(
                "--attempts", type=int, help="Times the model may fix what is found (default 3)"
            )
            p.add_argument("--write", action="store_true", help=f"Write {what} once it validates")
            p.add_argument("--yes", action="store_true", help="Do not ask before writing")
            p.add_argument(
                "--force", action="store_true", help="Write even if it does not validate"
            )
            UnifiedArgumentParser._add_output_format_arg(p, "Output format (json prints the draft)")

        quality = ai_sub.add_parser(
            "quality",
            help="Propose the quality checks of a node's output, proven on its data",
            description=(
                "Ducta measures the node's output in --env (column statistics only: the model "
                "never sees a row), the model proposes the node's `quality` block, and Ducta "
                "runs it on that data — a check that would fail goes back to the model."
            ),
        )
        quality.add_argument("pipeline", help="Pipeline holding the node")
        quality.add_argument("node", help="Node whose output to check")
        quality.add_argument("--env", default="dev", help="Environment whose data is measured")
        quality.add_argument("--note", help='What matters to you (e.g. "order_id is the key")')
        draft_args(quality, "the checks")

        document = ai_sub.add_parser(
            "document",
            help="Propose descriptions for undocumented datasets, pipelines and nodes",
            description=(
                "Adds a one-line description where there is none, and lists the columns that "
                "hold personal data (metadata.pii). Only what is missing is added; nothing "
                "else in the files changes."
            ),
        )
        document.add_argument("--env", default="dev", help="Environment whose data gives columns")
        document.add_argument("--note", help='Anything the model should know (e.g. "in Spanish")')
        draft_args(document, "the descriptions")

        explain = ai_sub.add_parser(
            "explain",
            help="Explain why a run failed and what to do, from its error",
            description=(
                "Ducta diagnoses the error (the kind of failure, the line of your code it was "
                "raised on); the model explains it in plain words. Nothing is changed. In the "
                "web app, a failed run's page explains it from the run itself."
            ),
        )
        explain.add_argument(
            "--error-file", required=True, help="File holding the error or traceback (- for stdin)"
        )
        explain.add_argument("--note", help="What you were doing, or what you already tried")
        UnifiedArgumentParser._add_discovery_args(explain)
        UnifiedArgumentParser._add_output_format_arg(explain, "Output format (json for scripts)")

        review = ai_sub.add_parser(
            "review",
            help="Review a pipeline, or one of its nodes: what Ducta is sure of, plus the model's view",
            description=(
                "Ducta checks first (a retried node that appends, runs near their timeout, I/O "
                "or collect() inside a function, credentials in the code, a pipeline with no "
                "owner or nothing checking its data…); the model adds what it sees in the code, "
                "the effective settings and the last runs. A finding of the model's that cites "
                "a node, line or setting that does not exist is dropped. Without NODE, the whole "
                "pipeline is reviewed and the model may suggest nodes to add (`ducta ai extend`). "
                "Nothing is changed."
            ),
        )
        review.add_argument("pipeline", help="Pipeline to review (or holding the node)")
        review.add_argument("node", nargs="?", help="Node to review (default: the whole pipeline)")
        review.add_argument(
            "--env", default="dev", help="Environment whose settings and runs to use"
        )
        review.add_argument("--note", help='What worries you (e.g. "it got slow last week")')
        review.add_argument(
            "--no-ai", action="store_true", help="Only Ducta's own checks: no model is asked"
        )
        review.add_argument(
            "--fail-on",
            choices=["high", "medium", "low"],
            help="Exit 3 when a finding is this severe or more (for CI)",
        )
        UnifiedArgumentParser._add_discovery_args(review)
        UnifiedArgumentParser._add_output_format_arg(review, "Output format (json for scripts)")

        revise = ai_sub.add_parser("revise", help="Ask for changes to a draft (a new draft)")
        revise.add_argument("draft_id", help="Draft id (or a unique prefix)")
        revise.add_argument("--note", required=True, help='What to change (e.g. "group by day")')
        UnifiedArgumentParser._add_discovery_args(revise)
        revise.add_argument(
            "--attempts", type=int, help="Times the model may fix validation problems (default 3)"
        )
        revise.add_argument(
            "--write", action="store_true", help="Write the draft once it validates"
        )
        revise.add_argument("--yes", action="store_true", help="Do not ask before writing")
        revise.add_argument(
            "--force", action="store_true", help="Write even if it does not validate"
        )
        UnifiedArgumentParser._add_output_format_arg(
            revise, "Output format (json prints the draft)"
        )

        drafts = ai_sub.add_parser("drafts", help="List the project's drafts")
        UnifiedArgumentParser._add_discovery_args(drafts)

        apply = ai_sub.add_parser("apply", help="Write a saved draft to the project")
        apply.add_argument("draft_id", help="Draft id (or a unique prefix), from `ducta ai new`")
        UnifiedArgumentParser._add_discovery_args(apply)
        apply.add_argument("--yes", action="store_true", help="Do not ask before writing")
        apply.add_argument(
            "--force", action="store_true", help="Write even if it does not validate"
        )

        UnifiedArgumentParser._add_agent_subcommands(ai_sub)

    @staticmethod
    def _add_agent_subcommands(ai_sub):
        """``ducta ai architect`` and ``ducta ai sentinel``: Ducta's agents."""
        fmt = UnifiedArgumentParser._add_output_format_arg
        discovery = UnifiedArgumentParser._add_discovery_args

        architect = ai_sub.add_parser(
            "architect",
            help="Ducta Architect: design pipelines as a blueprint, then build them",
            description=(
                "The model designs a blueprint (datasets, pipelines, contracts, logic in "
                "words); Ducta checks it without a model, writes the YAML itself and has "
                "the model write only the functions. `check` and `scaffold` need no model."
            ),
        )
        arch = architect.add_subparsers(dest="architect_command", required=True)
        plan = arch.add_parser("plan", help="Design a blueprint for a request (a draft)")
        plan.add_argument("request", help='What to build, e.g. "revenue per store and day"')
        plan.add_argument("--note", help="Answers to the model's questions, or what matters to you")
        plan.add_argument(
            "--attempts", type=int, help="Times the model may fix what is found (default 3)"
        )
        discovery(plan)
        fmt(plan, "Output format (json prints the draft)")
        check = arch.add_parser("check", help="Check a blueprint file without a model")
        check.add_argument("blueprint", help="The blueprint's YAML file")
        discovery(check)
        fmt(check, "Output format (json for scripts and assistants)")
        scaffold = arch.add_parser(
            "scaffold",
            help="Turn a blueprint file into a draft with stub functions, without a model",
        )
        scaffold.add_argument("blueprint", help="The blueprint's YAML file")
        scaffold.add_argument(
            "--write", action="store_true", help="Write the draft once it validates"
        )
        scaffold.add_argument("--yes", action="store_true", help="Do not ask before writing")
        discovery(scaffold)
        fmt(scaffold, "Output format (json prints the draft)")
        build = arch.add_parser(
            "build", help="Build a blueprint into one draft (the model writes the code)"
        )
        build.add_argument(
            "blueprint", help="A blueprint draft id (from `plan`) or a blueprint file"
        )
        build.add_argument(
            "--attempts", type=int, help="Times the model may fix each module (default 3)"
        )
        build.add_argument("--write", action="store_true", help="Write the draft once it validates")
        build.add_argument("--yes", action="store_true", help="Do not ask before writing")
        build.add_argument(
            "--force", action="store_true", help="Write even if it does not validate"
        )
        discovery(build)
        fmt(build, "Output format (json prints the draft)")
        verify = arch.add_parser(
            "verify", help="Validate built pipelines; run them in dev and snapshot their tests"
        )
        verify.add_argument("pipelines", nargs="*", help="Pipelines to verify (default: all)")
        verify.add_argument(
            "--env", default="dev", help="Where to run them (never a protected one)"
        )
        verify.add_argument("--run", action="store_true", help="Run them, in dependency order")
        verify.add_argument(
            "--tests", action="store_true", help="Write snapshot tests once they ran"
        )
        verify.add_argument("--start-date", help="For pipelines that require dates (YYYY-MM-DD)")
        verify.add_argument("--end-date", help="For pipelines that require dates (YYYY-MM-DD)")
        discovery(verify)
        fmt(verify, "Output format (json for scripts)")

        sentinel = ai_sub.add_parser(
            "sentinel",
            help="Ducta Sentinel: incidents for failed and late runs, safe re-runs outside prod",
            description=(
                "Rules decide: a failed run is diagnosed and a fixed table picks what to do. "
                "Re-runs happen only where sentinel: in ducta.yaml allows them, never in a "
                "protected environment; the rest is escalated, with an explanation and a fix "
                "draft from the model when one is configured. Only `watch` acts."
            ),
        )
        sen = sentinel.add_subparsers(dest="sentinel_command", required=True)
        status = sen.add_parser(
            "status", help="Whether Sentinel watches this project, and where it may act"
        )
        discovery(status)
        fmt(status, "Output format (json for scripts)")
        incidents = sen.add_parser("incidents", help="The project's incidents, newest first")
        incidents.add_argument(
            "--status",
            dest="incident_status",
            choices=["active", "open", "remediating", "escalated", "resolved", "ignored"],
            default="active",
            help="Which incidents (default: active)",
        )
        incidents.add_argument("--env", help="Only this environment's")
        discovery(incidents)
        fmt(incidents, "Output format (json for scripts and assistants)")
        show = sen.add_parser("show", help="One incident, with its timeline")
        show.add_argument("incident_id", help="Incident id")
        discovery(show)
        fmt(show, "Output format (json for scripts)")
        triage = sen.add_parser(
            "triage", help="What Sentinel would do about a run, without a model and without acting"
        )
        triage.add_argument("run_id", help="The run's certificate id")
        triage.add_argument("--env", help="Its environment (default: searched)")
        discovery(triage)
        fmt(triage, "Output format (json for scripts and assistants)")
        watch = sen.add_parser("watch", help="Run Sentinel: a pass every --interval seconds")
        watch.add_argument(
            "--env",
            action="append",
            dest="envs",
            help="Environment to watch (repeatable; default: all)",
        )
        watch.add_argument("--interval", type=float, default=60.0, help="Seconds between passes")
        watch.add_argument("--once", action="store_true", help="One pass, then exit (for cron)")
        watch.add_argument(
            "--rerun-timeout",
            type=float,
            default=4 * 3600.0,
            help="Seconds one re-run may take before it is stopped (default: 4 hours)",
        )
        discovery(watch)
        fmt(watch, "Output format (json prints each pass)")
        pause = sen.add_parser("pause", help="Stop Sentinel's re-runs on this project")
        pause.add_argument("--reason", default="", help="Why, for the audit log")
        discovery(pause)
        resume = sen.add_parser("resume", help="Let Sentinel act again")
        discovery(resume)
        for verb, what in (
            ("resolve", "Mark an incident resolved"),
            ("ignore", "Ignore an incident"),
        ):
            p_ = sen.add_parser(verb, help=what)
            p_.add_argument("incident_id", help="Incident id")
            p_.add_argument("--note", default="", help="Why, for its timeline")
            discovery(p_)
