"""A log message and an error are text, not Rich markup.

The console handler reads each line as markup, for the coloured prefix. The message went
through it too, so `ducta[api]` printed as `ducta`, and a `[/data/x.csv]` raised MarkupError
and the message was lost: on a failing run, that is the line you needed.
"""

from __future__ import annotations

import io

import pytest
from loguru import logger
from rich.console import Console

from ducta.console.ux.error_analyzer import classify_error, print_error_report
from ducta.console.ux.rich_logger import DUCTA_THEME, RichLoggerManager


@pytest.fixture
def console_log():
    """What the classic console view prints, through the real handler."""
    original = RichLoggerManager.console
    buffer = io.StringIO()
    RichLoggerManager.console = Console(file=buffer, theme=DUCTA_THEME, width=200)
    logger.remove()
    RichLoggerManager._add_rich_handler("INFO", verbose=False, show_path=False)
    yield buffer
    logger.remove()
    RichLoggerManager.console = original


@pytest.mark.parametrize(
    "message",
    [
        'pip install "ducta[api]"',
        "column [amount] is missing",
        "could not read [/data/orders.csv]",
        "[node_status] node_id=n status=running",
        "ends in a backslash \\",
        "<output_path>/<env> and {braces}",
    ],
)
def test_the_message_is_printed_as_written(console_log, message):
    logger.info("{}", message)
    assert message in console_log.getvalue()


def test_the_prefix_is_still_rendered(console_log):
    logger.info("hello")
    line = console_log.getvalue()
    assert "Ducta:" in line and "INFO" in line and "[accent]" not in line


def test_an_error_report_prints_a_bracketed_path():
    buffer = io.StringIO()
    analysis = classify_error("could not read [/data/orders.csv]", None)
    print_error_report(analysis, "n", console=Console(file=buffer, width=200))
    assert "[/data/orders.csv]" in buffer.getvalue()
