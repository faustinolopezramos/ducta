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
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from rich.console import Console
from rich.logging import RichHandler
from rich.rule import Rule
from rich.text import Text
from rich.theme import Theme
from rich.traceback import install as install_rich_traceback

PRIMARY = "default"  # Main text: adaptive to terminal foreground
BOLD_WHITE = "bold"
PRIMARY_BOLD = BOLD_WHITE
DIM_WHITE = "dim"
PRIMARY_DIM = DIM_WHITE

SUCCESS = "bold green"
WARNING = "bold yellow"
ERROR = "bold red"
INFO = "bold blue"

ACCENT = "bold cyan"  # Accent emphasis for DUCTA
NEUTRAL = DIM_WHITE  # Secondary text
MUTED = "dim"  # Muted text

TEXT_DEFAULT = BOLD_WHITE  # Primary text (adaptive)
TEXT_SECONDARY = "default"  # Secondary text (adaptive)

DUCTA_THEME = Theme(
    {
        "logging.level.debug": DIM_WHITE,
        "logging.level.info": INFO,
        "logging.level.warning": WARNING,
        "logging.level.error": ERROR,
        "logging.level.critical": "bold white on red",
        "info": INFO,
        "warning": WARNING,
        "error": ERROR,
        "success": SUCCESS,
        "debug": DIM_WHITE,
        "Ducta": ACCENT,
        "ducta": ACCENT,
        "pipeline": "bold",
        "node": "bold",
        "metric": "magenta",
        "highlight": "yellow",
        "dim": NEUTRAL,
        "accent": ACCENT,
    }
)
Ducta_THEME = DUCTA_THEME

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
    "pipeline_start": {"emoji": "▶", "style": "default"},
    "data_loading": {"emoji": "📥", "style": "default"},
    "execution": {"emoji": "⚙", "style": "default"},
    "schema": {"emoji": "📋", "style": "default"},
    "saving": {"emoji": "💾", "style": "default"},
    "success": {"emoji": "✓", "style": SUCCESS},
    "error": {"emoji": "✗", "style": ERROR},
}


class RichLoggerManager:
    """
    Professional logger configuration using Rich for elegant terminal output.
    """

    # Rich decides colour: a terminal gets it; a pipe, a file or a CI log gets
    # plain text (FORCE_COLOR=1 brings it back). force_terminal=True wrote
    # escape codes into every redirected log.
    console = Console(theme=Ducta_THEME, stderr=True)
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
            "CRITICAL": "bold white on red",
        }

        level_name = record["level"].name
        level_style = level_styles.get(level_name, PRIMARY)

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
        compact: bool = False,
    ) -> None:
        """
        Configure application logging with professional Rich formatting.

        *compact* is the CLI's default view (see ``ducta.console.ux.view``):
        the terminal shows the CLI's own messages, the engine's warnings and
        errors, and what the user's node code logs — without the time and level
        prefix. The log file still gets everything.
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

        if compact:
            logger.add(
                _compact_sink,
                format="{message}",
                level=console_level,
                filter=_compact_filter,
                colorize=False,
            )
        else:
            cls._add_rich_handler(console_level, verbose, show_path)

        cls._add_file_sink(log_file, file_logging, console_level)

    @classmethod
    def _add_rich_handler(cls, console_level: str, verbose: bool, show_path: bool) -> None:
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

    @classmethod
    def _add_file_sink(
        cls, log_file: Optional[str], file_logging: bool, console_level: str
    ) -> None:
        # The CLI always names the file: the project's `logs/ducta.log`, or none
        # outside a project (see `cli._log_file_for`). The cwd-relative default
        # below is for direct callers only. *file_logging* turns that default
        # off; an explicit *log_file* still wins, since it names a destination.
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


#: Below WARNING, the engine speaks to the log file, not the terminal.
_WARNING_NO = 30


def _compact_filter(record: Dict[str, Any]) -> bool:
    """What the compact terminal shows (the log file is not filtered)."""
    extra = record["extra"]
    if extra.get("console") is False or extra.get("node_error"):
        return False  # shown by ux.view instead (a node's error block)
    if extra.get("console") is True:
        return True
    name = record["name"] or ""
    if name.startswith("ducta.console"):
        return True  # the CLI's own messages are written for this terminal
    if name == "ducta" or name.startswith("ducta."):
        return record["level"].no >= _WARNING_NO
    return True  # the user's node code: what it logs is about their data


_COMPACT_STYLES = {
    "SUCCESS": ("✓ ", "bold green", ""),
    "WARNING": ("! ", "bold yellow", ""),
    "ERROR": ("✗ ", "bold red", ""),
    "CRITICAL": ("✗ ", "bold red", "bold"),
    "DEBUG": ("", "dim", "dim"),
}


def _compact_sink(message: Any) -> None:
    record = message.record
    level = record["level"].name
    name = record["name"] or ""
    text = Text()
    if not (name == "ducta" or name.startswith("ducta.")) and level in ("INFO", "DEBUG"):
        text.append("    · ", style="dim")  # under the node that logged it
        text.append(record["message"], style="dim")
    else:
        prefix, prefix_style, body_style = _COMPACT_STYLES.get(level, ("", "", ""))
        text.append(prefix, style=prefix_style)
        text.append(record["message"], style=body_style)
    with RichLoggerManager.get_lock():
        RichLoggerManager.console.print(text, soft_wrap=True)


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
    title = Text.assemble(("Ducta ", "bold white on blue"), (f" {version} ", "dim"))
    console.print(Rule(title, align="left", style="blue dim"))

    def _print_row(label: str, value: str):
        console.print(f"  [cyan]{label: <12}[/] [bold]{value}[/]")

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
    from ducta.console.ux import view

    if view.is_compact():
        return  # banners are classic-view furniture
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
    from ducta.console.ux import view

    if view.is_compact():
        view.node_started(node_name)  # its line is printed when it ends
        return
    console = RichLoggerManager.get_console()

    line = Text("  ")
    line.append(f"{ICONS['process']} ", style=PRIMARY)
    line.append(node_name, style=TEXT_DEFAULT)
    if node_type:
        line.append(f" [{node_type}]", style="dim")

    console.print(line)


def log_node_complete(
    node_name: str,
    duration: float = 0.0,
    records: int = 0,
    outputs: Optional[List[Tuple[str, Optional[int]]]] = None,
) -> None:
    """Log node execution completion with metrics.

    *outputs* — ``(dataset, rows)`` for each dataset the node wrote — is what
    the compact view shows on the node's line.
    """
    from ducta.console.ux import view

    if view.is_compact():
        view.node_finished(node_name, duration, outputs or [])
        return
    console = RichLoggerManager.get_console()

    line = Text("  ")
    line.append(f"{ICONS['complete']} ", style=SUCCESS)
    line.append(node_name, style=TEXT_DEFAULT)
    line.append(f" ({duration:.2f}s", style="dim")
    if records > 0:
        line.append(f", {records:,} records", style="dim")
    line.append(")", style="dim")

    console.print(line)
