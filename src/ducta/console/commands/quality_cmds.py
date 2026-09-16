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

import json
from typing import Any, List, Optional

from loguru import logger

from ducta.console.core import ExitCode


def _render_check_results_table(console, table, results: List[dict], header_text: str) -> None:
    """Render a list of check results into *table* (Check/Status/Severity/
    Message) and print it under *header_text*. Shared by ``_run`` and
    ``_report``, which build the same table from two differently-shaped
    service responses."""
    console.print(header_text)
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Severity")
    table.add_column("Message", style="white")
    for result in results:
        ok = result.get("passed", False)
        table.add_row(
            result.get("check_name", ""),
            "[green]✓ PASS[/green]" if ok else "[red]✗ FAIL[/red]",
            result.get("severity", ""),
            str(result.get("message", ""))[:80],
        )
    console.print(table)


def _resolve_storage_from_env(parsed_args) -> Optional[Any]:
    """Resolve a real project's quality-output storage backend from ``--env``."""
    env = getattr(parsed_args, "env", None)
    if not env:
        return None

    from ducta.check.engine import ValidationPhaseRunner
    from ducta.console.config import ConfigManager
    from ducta.console.execution import ContextInitializer

    config_manager = ConfigManager(
        base_path=getattr(parsed_args, "base_path", None),
        require_config=False,
    )
    config_manager.change_to_config_directory()
    context = ContextInitializer(config_manager).initialize(env)
    logger.info(
        "Resolving quality output via project Context for env '{}' "
        "(a Spark session may be required for non-JSON formats)...",
        env,
    )
    return ValidationPhaseRunner(context=context).storage


class QualityCommands:
    """Quality check CLI commands (ducta quality)."""

    @staticmethod
    def handle(parsed_args) -> int:
        cmd = getattr(parsed_args, "quality_command", None)
        if cmd == "list":
            return QualityCommands._list()
        elif cmd == "run":
            return QualityCommands._run(parsed_args)
        elif cmd == "report":
            return QualityCommands._report(parsed_args)
        elif cmd == "validate-config":
            return QualityCommands._validate_config(parsed_args)
        elif cmd == "trend":
            return QualityCommands._trend(parsed_args)
        elif cmd == "score":
            return QualityCommands._pipeline_score(parsed_args)
        else:
            logger.error("Unknown quality command: {}", cmd)
            return ExitCode.GENERAL_ERROR.value

    @staticmethod
    def _list() -> int:
        from ducta.check.service import QualityService
        from ducta.console.ux.formatters import create_table, get_console

        checks = QualityService.list_checks()
        console = get_console()
        table = create_table(title="Registered Quality Checks")

        if console and table:
            table.add_column("Name", style="cyan", no_wrap=True)
            table.add_column("Class", style="green")
            table.add_column("Module", style="dim")

            for check in checks:
                style = "dim" if check["origin"] == "built-in" else "bold yellow"
                table.add_row(
                    f"[{style}]{check['name']}[/{style}]", check["class_name"], check["module"]
                )

            console.print(table)
            console.print(f"\nTotal: [bold]{len(checks)}[/bold] checks registered")
        else:
            for check in checks:
                print(f"  {check['name']:40s} {check['class_name']} ({check['module']})")
            print(f"\nTotal: {len(checks)} checks registered")

        return ExitCode.SUCCESS.value

    @staticmethod
    def _run(parsed_args) -> int:
        from ducta.check.service import QualityService

        input_path = parsed_args.input
        file_format = getattr(parsed_args, "format", "parquet")
        config_path = parsed_args.config
        fail_fast = getattr(parsed_args, "fail_fast", False)
        output_format = getattr(parsed_args, "output_format", "rich")

        try:
            report = QualityService.run_checks(
                input_path=input_path,
                format=file_format,
                config_path=config_path,
                fail_fast=fail_fast,
            )
        except (FileNotFoundError, ValueError) as e:
            logger.error("Quality check error: {}", e)
            return ExitCode.VALIDATION_ERROR.value
        except Exception as e:
            logger.error("Quality run failed: {}", e)
            return ExitCode.GENERAL_ERROR.value

        if output_format == "json":
            print(json.dumps(report, indent=2, default=str))
        else:
            from ducta.console.ux.formatters import create_table, get_console

            console = get_console()
            table = create_table()
            if console and table:
                passed = report.get("passed", False)
                status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
                _render_check_results_table(
                    console, table, report.get("results", []), f"\nQuality Check Report — {status}"
                )
            else:
                print(json.dumps(report, indent=2, default=str))

        return (
            ExitCode.SUCCESS.value if report.get("passed", False) else ExitCode.GENERAL_ERROR.value
        )

    @staticmethod
    def _report(parsed_args) -> int:
        from ducta.check.service import QualityService

        dataset = parsed_args.dataset
        workspace = getattr(parsed_args, "workspace", ".")
        run_id = getattr(parsed_args, "run_id", None)
        all_reports = getattr(parsed_args, "all_reports", False)
        output_format = getattr(parsed_args, "output_format", "rich")
        pipeline_name = getattr(parsed_args, "pipeline", None)

        try:
            storage = _resolve_storage_from_env(parsed_args)
            result = QualityService.get_report(
                dataset=dataset,
                workspace=workspace,
                run_id=run_id,
                all_reports=all_reports,
                storage=storage,
                pipeline_name=pipeline_name,
            )
        except FileNotFoundError as e:
            logger.error("{}", e)
            return ExitCode.GENERAL_ERROR.value
        except Exception as e:
            logger.error("Failed to get report: {}", e)
            return ExitCode.GENERAL_ERROR.value

        if result.get("status") == "no_reports":
            logger.warning("{}", result.get("message", "No reports found"))
            return ExitCode.SUCCESS.value
        if result.get("status") == "list":
            print(f"Reports for '{dataset}':")
            for rid in result.get("run_ids", []):
                print(f"  {rid}")
            return ExitCode.SUCCESS.value

        if output_format == "json":
            print(json.dumps(result, indent=2, default=str))
        else:
            from ducta.console.ux.formatters import create_table, get_console

            console = get_console()
            table = create_table()
            if console and table:
                passed = result.get("passed", False)
                status_str = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
                _render_check_results_table(
                    console,
                    table,
                    result.get("results", []),
                    f"\nReport [cyan]{dataset}[/cyan] — {status_str}\n",
                )
            else:
                print(json.dumps(result, indent=2, default=str))

        return ExitCode.SUCCESS.value

    @staticmethod
    def _validate_config(parsed_args) -> int:
        from ducta.check.service import QualityService

        node_name = parsed_args.node
        config_path = parsed_args.config
        global_config_path = getattr(parsed_args, "global_config", None)

        try:
            result = QualityService.validate_node_config(
                node_name=node_name,
                config_path=config_path,
                global_config_path=global_config_path,
            )
        except Exception as e:
            logger.error("Validation failed: {}", e)
            return ExitCode.GENERAL_ERROR.value

        if not result["valid"]:
            logger.error("Quality config validation FAILED for node '{}'", node_name)
            for err in result.get("errors", []):
                logger.error("  ✗ {}", err)
            for warn in result.get("warnings", []):
                logger.warning("  ⚠ {}", warn)
            return ExitCode.VALIDATION_ERROR.value

        if result.get("warnings"):
            for warn in result["warnings"]:
                logger.warning("  ⚠ {}", warn)

        logger.info("Quality config for node '{}' is VALID", node_name)
        return ExitCode.SUCCESS.value

    @staticmethod
    def _trend(parsed_args) -> int:
        from ducta.check.service import QualityService

        dataset = parsed_args.dataset
        workspace = getattr(parsed_args, "workspace", ".")
        last_n = getattr(parsed_args, "last_n", 20)
        output_format = getattr(parsed_args, "output_format", "rich")
        pipeline_name = getattr(parsed_args, "pipeline", None)

        try:
            storage = _resolve_storage_from_env(parsed_args)
            result = QualityService.get_trend(
                dataset=dataset,
                workspace=workspace,
                last_n=last_n,
                storage=storage,
                pipeline_name=pipeline_name,
            )
        except Exception as e:
            logger.error("Failed to get trend: {}", e)
            return ExitCode.GENERAL_ERROR.value

        if result.get("status") == "no_trend":
            logger.warning("{}", result.get("message", "No trend data found"))
            return ExitCode.SUCCESS.value

        scores = result.get("scores", [])
        if output_format == "json":
            print(json.dumps(result, indent=2, default=str))
        else:
            from ducta.console.ux.formatters import create_table, get_console

            console = get_console()
            table = create_table(title=f"Quality Score Trend — {dataset} (last {len(scores)})")
            if console and table:
                table.add_column("#", style="dim", justify="right")
                table.add_column("Score", justify="right")
                table.add_column("Bar", no_wrap=True)
                for idx, score in enumerate(scores, 1):
                    bars = int(score * 20)
                    color = "green" if score >= 0.9 else ("yellow" if score >= 0.7 else "red")
                    table.add_row(
                        str(idx),
                        f"{score:.4f}",
                        f"[{color}]{'█' * bars}{'░' * (20 - bars)}[/{color}]",
                    )
                console.print(table)
            else:
                for i, s in enumerate(scores, 1):
                    print(f"{i:>3}: {s:.4f}")

        return ExitCode.SUCCESS.value

    @staticmethod
    def _pipeline_score(parsed_args) -> int:
        from ducta.check.service import QualityService

        run_id = parsed_args.run_id
        workspace = getattr(parsed_args, "workspace", ".")
        output_format = getattr(parsed_args, "output_format", "rich")

        try:
            storage = _resolve_storage_from_env(parsed_args)
            data = QualityService.get_score(run_id=run_id, workspace=workspace, storage=storage)
        except FileNotFoundError as e:
            logger.error("{}", e)
            return ExitCode.GENERAL_ERROR.value
        except Exception as e:
            logger.error("Failed to get pipeline score: {}", e)
            return ExitCode.GENERAL_ERROR.value

        if output_format == "json":
            print(json.dumps(data, indent=2, default=str))
        else:
            from ducta.console.ux.formatters import create_table, get_console

            console = get_console()
            if console:
                hi = float(data.get("health_index", 1.0))
                hi_color = "green" if hi >= 0.9 else ("yellow" if hi >= 0.7 else "red")
                console.print(f"\nPipeline Quality Score — run [bold]{run_id}[/bold]")
                console.print(
                    f"  Health Index: [{hi_color}]{hi:.4f}[/{hi_color}]  (sanity={data.get('sanity_score', 1.0):.4f}, dq={data.get('dq_score', 1.0):.4f})"
                )
                blocked = data.get("nodes_blocked", [])
                if blocked:
                    console.print(f"  Blocked nodes: [red]{', '.join(blocked)}[/red]")
                actions = data.get("gate_actions", {})
                if actions:
                    table = create_table(title="Gate Actions per Node")
                    if table:
                        table.add_column("Node", style="cyan")
                        table.add_column("Action")
                        for node, action in actions.items():
                            color = (
                                "green"
                                if action == "pass"
                                else ("yellow" if action == "warn" else "red")
                            )
                            table.add_row(node, f"[{color}]{action}[/{color}]")
                        console.print(table)
            else:
                print(json.dumps(data, indent=2, default=str))

        return ExitCode.SUCCESS.value
