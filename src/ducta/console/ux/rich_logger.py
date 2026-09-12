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

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger
from rich.console import Console
from rich.logging import RichHandler
from rich.rule import Rule
from rich.text import Text
from rich.theme import Theme
from rich.traceback import install as install_rich_traceback

PRIMARY = "bright_white"  # Color principal: Blanco brillante
BOLD_WHITE = "bold bright_white"
PRIMARY_BOLD = BOLD_WHITE
DIM_WHITE = "dim white"
PRIMARY_DIM = DIM_WHITE

SUCCESS = "bold bright_green"
WARNING = "bold bright_yellow"
ERROR = "bold bright_red"
INFO = "bold bright_blue"

ACCENT = "bold bright_cyan"  # Énfasis para "Ducta"
NEUTRAL = DIM_WHITE  # Texto secundario
MUTED = "dim"  # Muy atenuado

TEXT_DEFAULT = BOLD_WHITE  # Texto principal
TEXT_SECONDARY = "white"  # Texto secundario

Ducta_THEME = Theme(
    {
        "logging.level.debug": DIM_WHITE,
        "logging.level.info": INFO,
        "logging.level.warning": WARNING,
        "logging.level.error": ERROR,
        "logging.level.critical": "bold bright_white on bright_red",
        "info": INFO,
        "warning": WARNING,
        "error": ERROR,
        "success": SUCCESS,
        "debug": DIM_WHITE,
        "Ducta": ACCENT,
        "pipeline": PRIMARY,
        "node": PRIMARY,
        "metric": "bright_magenta",
        "highlight": "bright_yellow",
        "dim": NEUTRAL,
        "accent": ACCENT,
    }
)

ICONS = {
    "success": "✓",
    "error": "✗",
    "warning": "⚠",
    "info": "→",
    "process": "▸",
    "nested": "  ▸",
    "complete": "✓",
    "start": "▶",
    "end": "▬",
}

PROCESS_GROUPS = {
    "pipeline_start": {"emoji": "▶", "style": "white"},
    "data_loading": {"emoji": "📥", "style": "white"},
    "execution": {"emoji": "⚙", "style": "white"},
    "schema": {"emoji": "📋", "style": "white"},
    "saving": {"emoji": "💾", "style": "white"},
    "success": {"emoji": "✓", "style": SUCCESS},
    "error": {"emoji": "✗", "style": ERROR},
}


class RichLoggerManager:
    """
    Professional logger configuration using Rich for elegant terminal output.
    """

    console = Console(theme=Ducta_THEME, stderr=True, force_terminal=True)
    _lock = threading.RLock()  # Reentrant lock for thread-safety

    @classmethod
    def _determine_console_level(cls, verbose: bool, quiet: bool, level: str) -> str:
        """Determine console log level based on flags."""
        if quiet:
            return "ERROR"
        elif verbose:
            return "DEBUG"
        else:
            return level.upper()

    @staticmethod
    def _formatter(record: Dict[str, Any]) -> str:
        """
        Custom formatter for Ducta CLI to provide an elegant signature.
        """
        level_styles = {
            "DEBUG": DIM_WHITE,
            "INFO": INFO,
            "WARNING": WARNING,
            "ERROR": ERROR,
            "CRITICAL": "bold bright_white on bright_red",
        }

        level_name = record["level"].name
        level_style = level_styles.get(level_name, "white")

        prefix = "[accent]Ducta:[/] "
        time_str = record["time"].strftime("%H:%M:%S")
        time_tag = f"[dim][{time_str}][/] "
        level_tag = f"[{level_style}]{level_name: <8}[/] "

        return f"{prefix}{time_tag}{level_tag}{{message}}"

    @classmethod
    def setup(
        cls,
        level: str = "INFO",
        log_file: Optional[str] = None,
        verbose: bool = False,
        quiet: bool = False,
        show_time: bool = True,
        show_path: bool = False,
        enable_rich_tracebacks: bool = True,
        file_logging: bool = True,
    ) -> None:
        """
        Configure application logging with professional Rich formatting.
        """
        logger.enable("ducta")  # Library is disabled by default (see ducta/__init__.py)
        logger.remove()

        console_level = cls._determine_console_level(verbose, quiet, level)

        if enable_rich_tracebacks:
            install_rich_traceback(
                console=cls.console,
                show_locals=verbose,
                width=100,
                extra_lines=1,
                theme="github",
                word_wrap=True,
                suppress=[
                    "loguru",
                    "concurrent.futures",
                ],
                max_frames=10,
            )

        rich_handler = RichHandler(
            console=cls.console,
            show_time=False,
            show_level=False,
            show_path=show_path,
            markup=True,
            rich_tracebacks=True,
            tracebacks_show_locals=verbose,
            tracebacks_width=100,
            tracebacks_extra_lines=1,
            tracebacks_suppress=["loguru", "concurrent.futures"],
            omit_repeated_times=False,
        )

        logger.add(
            rich_handler,
            format=cls._formatter,
            level=console_level,
            colorize=False,  # Rich handles colors via markup
        )

        # The default sink is deliberately project-relative: `ducta template`
        # scaffolds a `logs/` directory and gitignores it, so a run inside a
        # project leaves its log next to the data it produced. That only holds
        # for commands that *operate on* a project. `ducta template` runs before
        # one exists, so creating `./logs/ducta.log` there wrote into whatever
        # directory the user happened to be standing in — and then
        # `validate_template_arguments` saw that very directory as "not empty"
        # and refused `--output-path .`, in a directory that had been empty a
        # moment earlier. Such commands pass file_logging=False; an explicit
        # --log-file still wins, since that names a destination outright.
        if not file_logging and not log_file:
            logger.debug("Rich logger initialized (console only, console_level={})", console_level)
            return

        log_path = Path(log_file) if log_file else Path("logs/ducta.log")

        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.add(
            log_path,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            rotation="10 MB",
            retention="7 days",
            level="DEBUG",
            compression="zip",
            enqueue=True,  # Thread-safe logging
        )

        logger.debug("Rich logger initialized (console_level={})", console_level)

    @classmethod
    def get_console(cls) -> Console:
        """Get the Rich console instance for custom output."""
        return cls.console

    @classmethod
    def get_lock(cls) -> threading.RLock:
        """Get the thread-safe lock for console operations."""
        return cls._lock


def print_execution_header(
    pipeline: str,
    env: str,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    node: Optional[str] = None,
) -> None:
    """
    Minimalist and elegant header for pipeline execution.
    """
    console = RichLoggerManager.get_console()

    try:
        from ducta import __version__

        version = f"v{__version__}"
    except ImportError:
        version = "unknown"

    console.print()
    title = Text.assemble(("Ducta ", "bold white on blue"), (f" {version} ", "dim white"))
    console.print(Rule(title, align="left", style="blue dim"))

    def _print_row(label: str, value: str):
        console.print(f"  [dim cyan]{label: <12}[/] [bold white]{value}[/]")

    _print_row("pipeline", pipeline)
    _print_row("env", env.upper())

    if node:
        _print_row("node", node)

    if start_date or end_date:
        start = (
            start_date.strftime("%Y-%m-%d")
            if hasattr(start_date, "strftime")
            else str(start_date or "...")
        )
        end = (
            end_date.strftime("%Y-%m-%d")
            if hasattr(end_date, "strftime")
            else str(end_date or "...")
        )
        _print_row("period", f"{start} ➔ {end}")

    _print_row("started", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    console.print(Rule(style="blue dim"))
    console.print()


def print_process_separator(
    process_type: str,
    title: str,
    subtitle: Optional[str] = None,
    console: Optional[Console] = None,
) -> None:
    """
    Print a simple text separator for process groups without borders.
    """
    if console is None:
        console = RichLoggerManager.console

    config = PROCESS_GROUPS.get(process_type, PROCESS_GROUPS["execution"])
    emoji = config["emoji"]
    style = config["style"]

    text = Text()
    text.append(f"{emoji} ", style=f"bold {style}")
    text.append(title, style=f"bold {style}")

    if subtitle:
        text.append("  •  ", style=NEUTRAL)
        text.append(subtitle, style=f"dim {style}")

    console.print(text)


def log_node_start(node_name: str, node_type: str = "") -> None:
    """Log node execution start with elegant formatting."""
    console = RichLoggerManager.get_console()

    line = Text("  ")
    line.append(f"{ICONS['process']} ", style=PRIMARY)
    line.append(node_name, style=TEXT_DEFAULT)
    if node_type:
        line.append(f" [{node_type}]", style="dim")

    console.print(line)


def log_node_complete(node_name: str, duration: float = 0.0, records: int = 0) -> None:
    """Log node execution completion with metrics."""
    console = RichLoggerManager.get_console()

    line = Text("  ")
    line.append(f"{ICONS['complete']} ", style=SUCCESS)
    line.append(node_name, style=TEXT_DEFAULT)
    line.append(f" ({duration:.2f}s", style="dim")
    if records > 0:
        line.append(f", {records:,} records", style="dim")
    line.append(")", style="dim")

    console.print(line)
