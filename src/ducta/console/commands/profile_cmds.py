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

``ducta profile``: assay a dataset and propose the spec it already satisfies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from loguru import logger  # type: ignore

from ducta.console.core import ExitCode


class ProfileCommands:
    """Entry point for ``ducta profile``."""

    @staticmethod
    def handle(parsed_args) -> int:
        from ducta.check.service import QualityService

        input_path = Path(parsed_args.input)
        if not input_path.exists():
            logger.error("Input file not found: {}", input_path)
            return ExitCode.VALIDATION_ERROR.value

        try:
            result = QualityService.profile(
                input_path=str(input_path),
                format=getattr(parsed_args, "format", "parquet"),
                strictness=getattr(parsed_args, "strictness", "balanced"),
                sample_rows=getattr(parsed_args, "sample_rows", None),
                dataset_name=getattr(parsed_args, "dataset_name", None),
            )
        except ValueError as e:
            logger.error("{}", e)
            return ExitCode.VALIDATION_ERROR.value
        except Exception as e:  # noqa: BLE001 — a bad file is the user's problem, not a crash
            logger.error("Could not profile '{}': {}", input_path, e)
            return ExitCode.GENERAL_ERROR.value

        if getattr(parsed_args, "output_format", "rich") == "json":
            print(json.dumps(result, indent=2, default=str))
        else:
            ProfileCommands._render(result["profile"])

        return ProfileCommands._emit_spec(result, getattr(parsed_args, "output", None))

    @staticmethod
    def _emit_spec(result: Dict[str, Any], output: Any) -> int:
        """Write the proposed spec to *output*, or print it when there is none."""
        spec_yaml = result["yaml"]
        if not output:
            print()
            print(spec_yaml)
            return ExitCode.SUCCESS.value

        destination = Path(output)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(spec_yaml, encoding="utf-8")
        except OSError as e:
            logger.error("Could not write the spec to '{}': {}", destination, e)
            return ExitCode.GENERAL_ERROR.value

        logger.success("Proposed spec written to {}", destination)
        logger.info(
            "Review it, then run it: ducta quality run --input {} --format {} --config {}",
            result["source"]["input_path"],
            result["source"]["format"],
            destination,
        )
        return ExitCode.SUCCESS.value

    @staticmethod
    def _render(profile: Dict[str, Any]) -> None:
        """Show the assay as a table, degrading to logs when Rich is absent.

        Same fallback shape as ``QualityReporter``: the decoration must never be
        the reason a command fails.
        """
        try:
            from rich.table import Table  # type: ignore

            from ducta.console.ux.rich_logger import RichLoggerManager

            console = RichLoggerManager.get_console()
            title = f"Profile: {profile['dataset_name']} — {profile['row_count']:,} rows"
            if profile.get("sampled"):
                title += f" (columns sampled from {profile['sample_rows']:,})"

            table = Table(title=title)
            for column, style in (
                ("Column", "cyan"),
                ("Type", "white"),
                ("Nulls", "yellow"),
                ("Distinct", "blue"),
                ("Range", "white"),
                ("Key", "green"),
            ):
                table.add_column(column, style=style)

            for column in profile["columns"]:
                table.add_row(
                    column["name"],
                    column["kind"],
                    f"{column['null_count']} ({column['null_rate']:.2%})",
                    "> cap" if column["distinct_count"] is None else str(column["distinct_count"]),
                    _format_range(column),
                    "✓" if column["is_key_candidate"] else "",
                )
            console.print()
            console.print(table)

            for gap in profile.get("gaps", []):
                console.print(f"[yellow]  not measured — {gap}[/]")
        except Exception:  # noqa: BLE001
            logger.info(
                "Profile of '{}': {} rows, {} columns",
                profile["dataset_name"],
                profile["row_count"],
                len(profile["columns"]),
            )
            for column in profile["columns"]:
                logger.info(
                    "  {} ({}): {} nulls, {} distinct",
                    column["name"],
                    column["kind"],
                    column["null_count"],
                    column["distinct_count"],
                )


def _format_range(column: Dict[str, Any]) -> str:
    minimum, maximum = column.get("minimum"), column.get("maximum")
    if minimum is None or maximum is None:
        return ""
    return f"{minimum:g} … {maximum:g}"


def handle_profile(parsed_args) -> int:
    return ProfileCommands.handle(parsed_args)


__all__ = ["ProfileCommands", "handle_profile"]
