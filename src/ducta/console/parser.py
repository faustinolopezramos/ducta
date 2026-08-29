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

HELP_BASE_PATH = "Base path for config discovery"
HELP_LAYER_NAME = "Layer name for config discovery"
HELP_USE_CASE = "Use case name"
HELP_CONFIG_TYPE = "Preferred configuration type"
HELP_PIPELINE_NAME = "Pipeline name"
HELP_PIPELINE_NAME_TO_EXECUTE = "Pipeline name to execute"
HELP_TIMEOUT_SECONDS = "Timeout in seconds"
HELP_CONFIG_FILE = "Path to configuration file"


class UnifiedArgumentParser:
    """Unified argument parser for all Ducta CLI commands."""

    @staticmethod
    def create() -> argparse.ArgumentParser:
        """Create configured argument parser with subcommands."""
        parser = argparse.ArgumentParser(
            prog="ducta",
            description="Ducta - Data Pipeline Framework",
            epilog="""
            Unified CLI with subcommands for all Ducta operations.

            Examples:
            # Direct pipeline execution
            ducta start --env dev --pipeline data_processing

            # Streaming pipelines
            ducta stream run --config config/streaming.py --pipeline real_time_processing
            ducta stream status --config config/streaming.py

            # Template generation
            ducta template --template medallion_basic --project-name my_project

            # Configuration management
            ducta config list-pipelines --env dev

            Note: Orchestration management (schedules, runs) is now exclusively available
            through the API REST interface. Use the API endpoints to manage pipeline
            orchestration, scheduling, and run management.
            """,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

        parser.add_argument("--version", action="store_true", help="Show Ducta signature & version")

        subparsers = parser.add_subparsers(
            dest="subcommand", help="Available subcommands", required=False
        )

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

        return parser

    @staticmethod
    def _add_start_subcommand(subparsers):
        start_parser = subparsers.add_parser(
            "start",
            help="Start pipelines directly",
            description="Start data pipelines directly without orchestration",
        )

        start_parser.add_argument(
            "--env",
            "-e",
            default="base",
            help="Execution environment (base, dev, sandbox, prod, or sandbox_<developer>). "
            "Defaults to 'base' when omitted.",
        )
        start_parser.add_argument("--pipeline", "-p", help=HELP_PIPELINE_NAME_TO_EXECUTE)
        start_parser.add_argument("--node", "-n", help="Specific node to execute (optional)")
        start_parser.add_argument(
            "--mode",
            "-m",
            choices=["sync", "async"],
            default="async",
            help="Execution mode for streaming/hybrid pipelines: 'async' (default, "
            "return once started) or 'sync' (block until terminating queries finish)",
        )
        start_parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
        start_parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
        start_parser.add_argument("--base-path", help=HELP_BASE_PATH)
        start_parser.add_argument("--layer-name", help=HELP_LAYER_NAME)
        start_parser.add_argument("--use-case", dest="use_case_name", help=HELP_USE_CASE)
        start_parser.add_argument(
            "--config-type", choices=["yaml", "json", "toml"], help=HELP_CONFIG_TYPE
        )
        start_parser.add_argument(
            "--interactive", action="store_true", help="Interactive config selection"
        )
        start_parser.add_argument(
            "--log-level",
            default="INFO",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            help="Logging level",
        )
        start_parser.add_argument("--log-file", help="Custom log file path")
        start_parser.add_argument(
            "--verbose", action="store_true", help="Enable verbose output (DEBUG)"
        )
        start_parser.add_argument("--quiet", action="store_true", help="Reduce output (ERROR only)")

        start_parser.add_argument("--model-version", help="Model version for ML pipelines")
        start_parser.add_argument("--hyperparams", help="Hyperparameters as JSON string")
        start_parser.add_argument(
            "--sweep",
            help="Hyperparameter sweep spec (YAML/JSON file). List values are expanded into the cartesian product and one run is executed per combination, all tagged with a common sweep_id in the experiment tracker",
        )

        start_parser.add_argument(
            "--search",
            action="store_true",
            help="Drive a real search strategy from the pipeline's hyperparams_config "
            "(algorithm: grid|random|bayesian, honoring n_trials and objective.metric) "
            "instead of the flat cartesian product --sweep expands. Each trial's "
            "objective value is fed back to the strategy, so Bayesian search learns "
            "between trials",
        )
        start_parser.add_argument(
            "--search-metric",
            help="Objective metric to optimize, overriding hyperparams_config.objective.metric. "
            "Point it at a validation metric: selecting on a test metric invalidates it",
        )
        start_parser.add_argument(
            "--search-trials",
            type=int,
            help="Trial budget for --search (random/bayesian), overriding n_trials",
        )
        start_parser.add_argument(
            "--no-sweep-reuse",
            action="store_true",
            help="Recompute every node on each sweep/search trial. By default the "
            "trial-invariant upstream nodes are materialized once and reused, since "
            "trials differ only in hyperparameters",
        )
        start_parser.add_argument(
            "--sweep-parallel",
            type=int,
            default=1,
            metavar="N",
            help="Run N sweep/search trials concurrently, each in its own process and "
            "its own output directory. Mutually exclusive with upstream reuse (an "
            "isolated trial has nothing shared to reuse), and not applied to Bayesian "
            "search, which needs each trial's result before choosing the next. Use it "
            "when training dominates the runtime, and --no-sweep-reuse off (the "
            "default) when feature engineering does",
        )
        start_parser.add_argument(
            "--max-sweep-size",
            type=int,
            default=None,
            metavar="N",
            help="Cap on the number of combinations a --sweep/--search grid may expand "
            "to (default: 50). Mirrors the API's max_sweep_size setting for the CLI path",
        )

        start_parser.add_argument(
            "--validate-only",
            action="store_true",
            help="Validate configuration without executing the pipeline",
        )
        start_parser.add_argument(
            "--dry-run", action="store_true", help="Log actions without executing the pipeline"
        )
        start_parser.add_argument(
            "--sanity-only",
            action="store_true",
            help="Run sanity checks on all node inputs without executing the pipeline",
        )
        start_parser.add_argument(
            "--reuse-upstream",
            action="store_true",
            help="In a depends_on chain, skip upstream pipelines whose outputs are "
            "already materialized (reads them from disk instead of recomputing)",
        )
        start_parser.add_argument(
            "--rerun-all",
            action="store_true",
            help="Force the full depends_on chain to re-run, ignoring any chain-reuse "
            "configuration",
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
        run_parser.add_argument("--config", "-c", required=True, help=HELP_CONFIG_FILE)
        run_parser.add_argument("--pipeline", "-p", required=True, help="Pipeline name to execute")
        run_parser.add_argument(
            "--env",
            "-e",
            default="base",
            help="Execution environment (base, dev, prod, …). Requires environment.toml in the project root.",
        )
        run_parser.add_argument(
            "--mode",
            "-m",
            default="async",
            choices=["sync", "async"],
            help="Execution mode for streaming pipelines",
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

        status_parser = stream_subparsers.add_parser(
            "status", help="Check streaming pipeline status"
        )
        status_parser.add_argument("--config", "-c", required=True, help=HELP_CONFIG_FILE)
        status_parser.add_argument("--env", default="base", help="Execution environment")
        status_parser.add_argument("--execution-id", "-e", help="Specific execution ID to check")
        status_parser.add_argument(
            "--format", "-f", default="table", choices=["table", "json"], help="Output format"
        )

        stop_parser = stream_subparsers.add_parser("stop", help="Stop streaming pipeline")
        stop_parser.add_argument("--config", "-c", required=True, help=HELP_CONFIG_FILE)
        stop_parser.add_argument("--env", default="base", help="Execution environment")
        stop_parser.add_argument("--execution-id", "-e", required=True, help="Execution ID to stop")
        stop_parser.add_argument("--timeout", "-t", type=int, default=60, help=HELP_TIMEOUT_SECONDS)

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
            "--format",
            choices=["yaml", "json", "toml"],
            default="yaml",
            help="Config format for generated template",
        )
        template_parser.add_argument(
            "--sandbox-developers",
            nargs="*",
            help="List of developer names for sandbox environments",
        )
        template_parser.add_argument(
            "--no-sample-code",
            action="store_true",
            help="Do not include sample code in generated template",
        )
        template_parser.add_argument(
            "--list-templates", action="store_true", help="List available templates"
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

        config_subparsers.add_parser("list-configs", help="List discovered configs")

        list_pipelines_parser = config_subparsers.add_parser(
            "list-pipelines", help="List available pipelines"
        )
        list_pipelines_parser.add_argument("--env", help="Environment to use for listing")
        list_pipelines_parser.add_argument(
            "--filter",
            dest="filter_pattern",
            default=None,
            help="Filter pipelines by name (case-insensitive substring match)",
        )
        list_pipelines_parser.add_argument(
            "--format",
            dest="output_format",
            choices=["table", "json", "list"],
            default="table",
            help="Output format: table (default), json, or list",
        )

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
        validate_parser.add_argument(
            "--pipeline",
            default=None,
            help="Pipeline to validate (default: all pipelines)",
        )
        validate_parser.add_argument("--env", help="Environment to use")

        config_subparsers.add_parser("clear-cache", help="Clear configuration cache")

        config_parser.add_argument("--base-path", help=HELP_BASE_PATH)
        config_parser.add_argument("--layer-name", help=HELP_LAYER_NAME)
        config_parser.add_argument("--use-case", dest="use_case_name", help=HELP_USE_CASE)
        config_parser.add_argument(
            "--config-type", choices=["yaml", "json", "toml"], help=HELP_CONFIG_TYPE
        )
        config_parser.add_argument(
            "--interactive", action="store_true", help="Interactive config selection"
        )

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
        run_qp.add_argument(
            "--output-format",
            default="rich",
            choices=["rich", "json"],
            help="Report output format (default: rich)",
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
        report_qp.add_argument(
            "--output-format",
            default="rich",
            choices=["rich", "json"],
            help="Report output format (default: rich)",
        )
        report_qp.add_argument(
            "--env",
            "-e",
            help="Environment to resolve the project's real quality.output "
            "storage from (base, dev, sandbox, prod, ...), instead of the "
            "standalone --workspace/.quality convention used by "
            "'ducta quality run'. Reads reports a real pipeline run persisted.",
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
        trend_qp.add_argument(
            "--output-format",
            default="rich",
            choices=["rich", "json"],
            help="Output format (default: rich)",
        )
        trend_qp.add_argument(
            "--env",
            "-e",
            help="Environment to resolve the project's real quality.output "
            "storage from, instead of the standalone --workspace convention.",
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
        score_qp.add_argument(
            "--output-format",
            default="rich",
            choices=["rich", "json"],
            help="Output format (default: rich)",
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
            "--config", "-c", required=True, help="Path to nodes config file (TOML/YAML)"
        )
        validate_qp.add_argument(
            "--global-settings", "-g", help="Path to global_settings file (for profile resolution)"
        )

    @staticmethod
    def _add_experiment_subcommand(subparsers):
        exp_parser = subparsers.add_parser(
            "experiment",
            help="Manage MLOps experiments",
            description="List and inspect MLOps experiment tracking data",
        )
        exp_sub = exp_parser.add_subparsers(
            dest="experiment_command", help="Experiment commands", required=True
        )
        list_p = exp_sub.add_parser("list", help="List recent experiments")
        list_p.add_argument(
            "--storage-path",
            help="MLOps storage path (Optional, auto-discovered by default)",
            default=None,
        )
        list_p.add_argument(
            "--env",
            help="Project environment to resolve the storage path from "
            "(e.g. dev, prod) — auto-discovery requires this",
            default=None,
        )
        list_p.add_argument(
            "--pipeline",
            help="Pipeline name (schema.pipeline) to resolve a per-pipeline "
            "storage path — matches how a real run resolves its own path when "
            "no global 'mlops_path' override is set. Omit to look at the "
            "environment's shared/default MLOps directory instead.",
            default=None,
        )
        list_p.add_argument(
            "--limit",
            type=int,
            help="Maximum number of experiments to show (default: all)",
            default=None,
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
        prom_p.add_argument("version", help="Model version")
        prom_p.add_argument(
            "stage", choices=["staging", "production", "archived"], help="Target stage"
        )
        prom_p.add_argument(
            "--storage-path",
            help="MLOps storage path (Optional, auto-discovered by default)",
            default=None,
        )
        prom_p.add_argument(
            "--env",
            help="Project environment to resolve the storage path from "
            "(e.g. dev, prod) — auto-discovery requires this",
            default=None,
        )
        prom_p.add_argument(
            "--pipeline",
            help="Pipeline name (schema.pipeline) to resolve a per-pipeline "
            "storage path — matches how a real run resolves its own path when "
            "no global 'mlops_path' override is set.",
            default=None,
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
        gc_p.add_argument(
            "--storage-path",
            help="MLOps storage path (Optional, auto-discovered by default)",
            default=None,
        )
        gc_p.add_argument(
            "--env",
            help="Project environment to resolve the storage path from "
            "(e.g. dev, prod) — auto-discovery requires this",
            default=None,
        )
        gc_p.add_argument(
            "--pipeline",
            help="Pipeline name (schema.pipeline) to resolve a per-pipeline "
            "storage path — matches how a real run resolves its own path when "
            "no global 'mlops_path' override is set. Omit to garbage-collect "
            "the environment's shared/default MLOps directory instead.",
            default=None,
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
                "(.ducta/runs/<run_id>/certificate.json). List, show, or verify them."
            ),
        )
        certify_subparsers = certify_parser.add_subparsers(
            dest="certify_command", help="Certificate commands", required=True
        )

        list_parser = certify_subparsers.add_parser("list", help="List run certificates")
        list_parser.add_argument("--dir", help="Runs directory (default: .ducta/runs)")
        list_parser.add_argument(
            "--env", help="Environment to scope the search to (default: search all environments)"
        )

        show_parser = certify_subparsers.add_parser(
            "show", help="Show a certificate (human-readable by default)"
        )
        show_parser.add_argument("--run-id", required=True, help="Run id (or a unique prefix)")
        show_parser.add_argument("--dir", help="Runs directory (default: .ducta/runs)")
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
        verify_parser.add_argument("--dir", help="Runs directory (default: .ducta/runs)")
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
        diff_parser.add_argument("--dir", help="Runs directory (default: .ducta/runs)")
        diff_parser.add_argument(
            "--env", help="Environment to scope the search to (default: search all environments)"
        )
