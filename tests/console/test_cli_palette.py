"""The CLI must stay readable on light and dark terminals.

A fixed white foreground disappears on a light theme, and the terminal's own
foreground on a forced black background disappears on a light theme too. Text
may only be white when it also sets its own background (``white on red``).
"""

from __future__ import annotations

from typing import Iterable

import pytest

pytest.importorskip("rich")

from rich.console import Console  # noqa: E402
from rich.style import Style  # noqa: E402
from rich.table import Table  # noqa: E402

from ducta.console.ux import formatters, rich_logger, schema_formatter  # noqa: E402

_WHITES = {"white", "bright_white"}


def _unreadable(style: object) -> bool:
    if not style:
        return False
    try:
        parsed = style if isinstance(style, Style) else Style.parse(str(style))
    except Exception:  # a theme name such as rich's own "table.header"
        return False
    fg = parsed.color.name if parsed.color else None
    bg = parsed.bgcolor.name if parsed.bgcolor else None
    white_on_nothing = fg in _WHITES and bg is None
    nothing_on_black = bg in {"black", "bright_black"} and fg in (None, "default")
    return white_on_nothing or nothing_on_black


def _table_styles(table: Table) -> Iterable[object]:
    yield table.header_style
    yield table.border_style
    yield from table.row_styles
    for column in table.columns:
        yield column.style
        yield column.header_style


def test_palette_constants_adapt_to_the_terminal():
    for name in ("PRIMARY", "PRIMARY_BOLD", "PRIMARY_DIM", "TEXT_SECONDARY"):
        assert not _unreadable(getattr(rich_logger, name)), name
    # Only Ducta's own entries: the theme also carries rich's defaults.
    ours = ["logging.level.debug", "logging.level.info", "logging.level.warning"]
    ours += ["logging.level.error", "logging.level.critical", "pipeline", "node", "metric"]
    ours += ["highlight", "dim", "accent", "info", "warning", "error", "debug"]
    styles = rich_logger.DUCTA_THEME.styles
    assert not [k for k in ours if k in styles and _unreadable(styles[k])]


def test_schema_table_uses_the_shared_palette():
    table = schema_formatter._build_schema_table("Schema", "Spark", 3)
    assert not [s for s in _table_styles(table) if _unreadable(s)]
    assert schema_formatter.PRIMARY == rich_logger.PRIMARY
    assert not _unreadable(schema_formatter._get_type_color("unknown"))


def test_status_dashboard_header_is_readable(monkeypatch):
    built: list[Table] = []

    class RecordingTable(formatters.Table):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            built.append(self)

    console = Console(record=True, width=120)
    monkeypatch.setattr(formatters, "Table", RecordingTable)
    monkeypatch.setattr(
        formatters.PipelineStatusFormatter, "_get_console", staticmethod(lambda: console)
    )

    formatters.PipelineStatusFormatter.format_multiple_pipelines(
        [{"pipeline_name": "sales", "status": "weird", "nodes": [], "execution_time": 1.0}]
    )

    assert built, "the dashboard printed no table"
    for table in built:
        assert not [s for s in _table_styles(table) if _unreadable(s)]
    assert not _unreadable(formatters.PipelineStatusFormatter._get_status_color("unknown"))
