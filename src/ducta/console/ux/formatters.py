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

Professional Rich formatters for pipeline status and execution display.
"""

from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table

    from ducta.console.ux.rich_logger import (
        ERROR,
        ICONS,
        PRIMARY,
        PRIMARY_BOLD,
        PRIMARY_DIM,
        SUCCESS,
        WARNING,
        RichLoggerManager,
    )

    _USE_RICH = True
except ImportError:
    _USE_RICH = False
    logger.debug("Rich or ducta.ux.rich_logger not available, using basic formatting")


class PipelineStatusFormatter:
    """Professional formatter for pipeline status with elegant visual design."""

    @staticmethod
    def _get_console():
        """Return the active Rich console, or None when Rich is unavailable."""
        return get_console()

    STATUS_COLOR_MAP = {
        "completed": SUCCESS,
        "running": WARNING,
        "failed": ERROR,
        "pending": "blue",
    }

    STATUS_EMOJI_MAP = {
        "completed": ICONS.get("success", "✅"),
        "running": "🔄",
        "failed": ICONS.get("error", "❌"),
        "pending": "⏳",
    }

    @staticmethod
    def _get_status_color(status: str) -> str:
        """Get color for status value."""
        return PipelineStatusFormatter.STATUS_COLOR_MAP.get(status.lower(), "white")

    @staticmethod
    def _get_status_emoji(status: str) -> str:
        """Get emoji for status value."""
        return PipelineStatusFormatter.STATUS_EMOJI_MAP.get(status.lower(), "❓")

    @staticmethod
    def format_single_pipeline(status_info: Dict[str, Any]) -> None:
        """Format and print status for a single pipeline."""
        console = PipelineStatusFormatter._get_console()
        if not _USE_RICH or not console:
            logger.info("Pipeline Status: {}", status_info)
            return

        pipeline_name = status_info.get("pipeline_name", "Unknown")
        status = status_info.get("status", "Unknown")
        nodes = status_info.get("nodes", [])
        execution_time = status_info.get("execution_time", 0.0)
        environment = status_info.get("environment", "N/A")

        table = Table(
            title=f"[{PRIMARY_BOLD}]Pipeline:[/] [white]{pipeline_name}[/]",
            box=box.ROUNDED,
            show_header=True,
            header_style=PRIMARY_BOLD,
            border_style=PRIMARY,
        )

        table.add_column("Property", style=PRIMARY, no_wrap=True)
        table.add_column("Value", style="white")

        status_color = PipelineStatusFormatter._get_status_color(status)

        table.add_row("Status", f"[bold {status_color}]{status.upper()}[/]")
        table.add_row("Environment", f"[{WARNING}]{environment}[/]")
        table.add_row("Execution Time", f"{execution_time:.2f}s")
        table.add_row("Total Nodes", str(len(nodes)))

        if nodes:
            completed_nodes = sum(1 for n in nodes if n.get("status") == "completed")
            table.add_row("Completed Nodes", f"{completed_nodes}/{len(nodes)}")

        console.print(table)

        if nodes:
            nodes_table = Table(
                title=f"[{PRIMARY_BOLD}]Nodes Execution Details[/]",
                box=box.SIMPLE,
                show_header=True,
                header_style=PRIMARY_BOLD,
                border_style=PRIMARY_DIM,
            )

            nodes_table.add_column("Node", style=PRIMARY)
            nodes_table.add_column("Status", justify="center")
            nodes_table.add_column("Duration", justify="right", style=SUCCESS)

            for node in nodes:
                node_name = node.get("name", "Unknown")
                node_status = node.get("status", "unknown")
                node_duration = node.get("duration", 0.0)

                status_emoji = PipelineStatusFormatter._get_status_emoji(node_status)

                nodes_table.add_row(
                    node_name, f"{status_emoji} {node_status}", f"{node_duration:.2f}s"
                )

            console.print(nodes_table)

    @staticmethod
    def _build_pipeline_row(idx: int, status_info: Dict[str, Any]) -> Tuple[str, ...]:
        """Build a summary table row for a single pipeline status entry."""
        pipeline_name = status_info.get("pipeline_name", "Unknown")
        status = status_info.get("status", "Unknown")
        nodes = status_info.get("nodes", [])
        execution_time = status_info.get("execution_time", 0.0)
        environment = status_info.get("environment", "N/A")

        status_key = status.lower()
        if status_key in PipelineStatusFormatter.STATUS_COLOR_MAP:
            color = PipelineStatusFormatter._get_status_color(status)
            emoji = PipelineStatusFormatter._get_status_emoji(status)
            status_display = f"[{color}]{emoji} {status_key.capitalize()}[/]"
        else:
            status_display = f"[white]❓ {status}[/]"

        progress = PipelineStatusFormatter._calculate_progress(nodes)

        duration_display = PipelineStatusFormatter._format_duration(execution_time)

        return (str(idx), pipeline_name, environment, status_display, progress, duration_display)

    @staticmethod
    def _calculate_progress(nodes: List[Dict[str, Any]]) -> str:
        """Calculate and format progress display for nodes."""
        if not nodes:
            return "[dim]-[/]"

        completed = sum(1 for n in nodes if n.get("status") == "completed")
        failed = sum(1 for n in nodes if n.get("status") == "failed")
        total = len(nodes)

        if failed > 0:
            return f"[{ERROR}]{completed}[/]/[{PRIMARY_DIM}]{total}[/] [{ERROR}]({failed}❌)[/]"
        return f"[{SUCCESS}]{completed}[/]/[{PRIMARY_DIM}]{total}[/]"

    @staticmethod
    def _format_duration(execution_time: float) -> str:
        """Format execution time into human-readable format."""
        if execution_time >= 60:
            return f"{execution_time / 60:.1f}m"
        return f"{execution_time:.1f}s"

    @staticmethod
    def format_multiple_pipelines(status_list: List[Dict[str, Any]]) -> None:
        """Format and print status for multiple pipelines with elegant summary."""
        console = PipelineStatusFormatter._get_console()
        if not _USE_RICH or not console:
            for status in status_list:
                logger.info("Pipeline Status: {}", status)
            return

        console.print()
        console.print(Rule(f"[{PRIMARY_BOLD}]🚀 Pipelines Status Dashboard[/]", style=PRIMARY))
        console.print()

        table = Table(
            box=box.DOUBLE_EDGE,
            show_header=True,
            header_style=f"bold {PRIMARY} on black",
            border_style=PRIMARY,
            row_styles=[PRIMARY_DIM, ""],
            padding=(0, 1),
        )

        table.add_column("№", style=PRIMARY_DIM, width=4, justify="right")
        table.add_column("Pipeline", style=PRIMARY, no_wrap=True, min_width=20)
        table.add_column("Environment", style=WARNING, justify="center", width=12)
        table.add_column("Status", justify="center", width=18)
        table.add_column("Progress", justify="center", width=12)
        table.add_column("Duration", justify="right", style=SUCCESS, width=10)

        for idx, status_info in enumerate(status_list, 1):
            row = PipelineStatusFormatter._build_pipeline_row(idx, status_info)
            table.add_row(*row)

        console.print(table)

        # Summary statistics
        total_pipelines = len(status_list)
        completed_count = sum(1 for s in status_list if s.get("status", "").lower() == "completed")
        failed_count = sum(1 for s in status_list if s.get("status", "").lower() == "failed")
        running_count = sum(1 for s in status_list if s.get("status", "").lower() == "running")

        summary_table = Table.grid(padding=(0, 2))
        summary_table.add_column(style=PRIMARY_DIM)
        summary_table.add_column(style=PRIMARY_BOLD)

        summary_table.add_row("Total:", str(total_pipelines))
        summary_table.add_row("Completed:", f"[{SUCCESS}]{completed_count}[/]")
        if running_count > 0:
            summary_table.add_row("Running:", f"[{WARNING}]{running_count}[/]")
        if failed_count > 0:
            summary_table.add_row("Failed:", f"[{ERROR}]{failed_count}[/]")

        console.print()
        console.print(
            Panel(
                summary_table,
                title=f"[{PRIMARY_BOLD}]Summary[/]",
                border_style=PRIMARY_DIM,
                box=box.ROUNDED,
                padding=(0, 2),
            )
        )
        console.print()


# ── Helper functions for CLI to avoid direct Rich imports ──────────────────


def get_console() -> Optional["Console"]:
    """Get the Rich console instance, or None if Rich is unavailable."""
    if not _USE_RICH:
        return None
    return RichLoggerManager.get_console()


def create_table(title: Optional[str] = None, **kwargs: Any) -> Optional["Table"]:
    """Create a Rich Table instance, or None if Rich is unavailable.

    Args:
        title: Optional title for the table
        **kwargs: Additional arguments to pass to Table constructor

    Returns:
        A Rich Table instance or None if Rich is unavailable
    """
    if not _USE_RICH:
        return None
    return Table(title=title, **kwargs)


def require_table(title: Optional[str] = None, **kwargs: Any) -> "Table":
    """`create_table` for callers that have already established Rich is present.

    Most render paths open with a ``if console is None or not _USE_RICH: return``
    guard and then build several tables. `create_table`'s honest `Optional`
    return type cannot see that guard, so each of those builders reads as
    "might be None" and every `.add_column` after it looks like a possible
    `AttributeError` — dozens of warnings over a branch that cannot be taken,
    which is how a real one would go unnoticed. Past the guard, use this.
    """
    table = create_table(title=title, **kwargs)
    if table is None:  # pragma: no cover — unreachable past a _USE_RICH guard
        raise RuntimeError(
            "require_table() called without Rich available; check _USE_RICH "
            "(or get_console()) before building tables."
        )
    return table
