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

import re
from typing import Optional, Tuple

from rich import box  # type: ignore
from rich.console import Console  # type: ignore
from rich.table import Table  # type: ignore
from rich.text import Text  # type: ignore

PRIMARY = "white"
BOLD_WHITE = "bold white"
PRIMARY_BOLD = BOLD_WHITE
PRIMARY_DIM = "dim white"


def parse_spark_schema_line(line: str) -> Optional[Tuple[str, str, str, int]]:
    """
    Parse a single line from Spark's printSchema() output.
    """
    # Match pattern like: " |-- Field: type (nullable = true)"
    pattern = r"^(\s*\|--\s+)([^:]+):\s+([^(]+)\(nullable\s*=\s*(true|false)\)"
    match = re.match(pattern, line)

    if match:
        indent = match.group(1)
        field_name = match.group(2).strip()
        data_type = match.group(3).strip()
        nullable = match.group(4)
        indent_level = (len(indent) - 4) // 4  # Calculate nesting level
        return (field_name, data_type, nullable, indent_level)

    return None


def _build_schema_table(title: str, source_label: str, field_count: int) -> Table:
    """Build the (empty) elegant schema table shared by the Spark and pandas
    formatters, which differ only in *source_label* and their rows."""
    table = Table(
        title=f"[{PRIMARY_BOLD}]🔧 {title}[/] [{PRIMARY_DIM}]{source_label} • {field_count} fields[/]",
        box=box.ROUNDED,
        border_style="white",
        header_style="bold white on black",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("№", style=PRIMARY_DIM, width=4, justify="right")
    table.add_column("Field Name", style="white", no_wrap=True, min_width=20)
    table.add_column("Data Type", style=PRIMARY_DIM, justify="center", width=15)
    table.add_column("Nullable", style="white", justify="center", width=10)
    return table


def _nullable_display(is_nullable: bool) -> str:
    icon = "✓" if is_nullable else "✗"
    style = "white" if is_nullable else PRIMARY_DIM
    return f"[{style}]{icon}[/]"


def _render_schema_footer(console: Console, table: Table, field_count: int) -> None:
    footer = Text()
    footer.append("Total Fields: ", style="dim")
    footer.append(f"{field_count}", style=BOLD_WHITE)

    console.print()
    console.print(table)
    console.print("  ", footer)
    console.print()


def print_spark_schema(
    schema_text: str, title: str = "DataFrame Schema", console: Console = None
) -> None:
    """
    Display Spark DataFrame schema in an elegant table format.
    """
    if console is None:
        console = Console()

    lines = schema_text.strip().split("\n")
    fields = []

    for line in lines:
        if line.strip().startswith("|--"):
            parsed = parse_spark_schema_line(line)
            if parsed:
                fields.append(parsed)

    if not fields:
        console.print("[yellow]No schema fields found to display[/]")
        return

    table = _build_schema_table(title, "Apache Spark DataFrame", len(fields))

    for idx, (field_name, data_type, nullable, indent_level) in enumerate(fields, 1):
        # Add indentation for nested fields
        display_name = "  " * indent_level + field_name
        type_style = _get_type_color(data_type)
        table.add_row(
            str(idx),
            display_name,
            f"[{type_style}]{data_type}[/]",
            _nullable_display(nullable == "true"),
        )

    _render_schema_footer(console, table, len(fields))


def print_pandas_schema(
    df: object, title: str = "DataFrame Schema", console: Console = None
) -> None:
    """Display a pandas DataFrame schema in the same table format as Spark."""
    if console is None:
        console = Console()

    try:
        columns = list(df.columns)  # type: ignore[attr-defined]
        dtypes = df.dtypes  # type: ignore[attr-defined]
    except Exception:
        console.print("[yellow]No schema fields found to display[/]")
        return

    if not columns:
        console.print("[yellow]No schema fields found to display[/]")
        return

    table = _build_schema_table(title, "Pandas DataFrame", len(columns))

    for idx, col in enumerate(columns, 1):
        data_type = (
            str(dtypes[col]) if col in getattr(dtypes, "index", []) else str(dtypes[idx - 1])
        )
        try:
            has_nulls = bool(df[col].isnull().any())  # type: ignore[index]
        except Exception:
            has_nulls = True

        type_style = _get_type_color(data_type)
        table.add_row(
            str(idx),
            str(col),
            f"[{type_style}]{data_type}[/]",
            _nullable_display(has_nulls),
        )

    _render_schema_footer(console, table, len(columns))


def _get_type_color(data_type: str = "") -> str:
    """Return a Rich color for a Spark/pandas data type string."""
    dt = data_type.lower()
    if any(t in dt for t in ("int", "long", "short", "byte", "decimal", "double", "float")):
        return "bright_cyan"
    if any(t in dt for t in ("string", "char", "varchar", "object", "category")):
        return "bright_green"
    if "bool" in dt:
        return "bright_yellow"
    if any(t in dt for t in ("date", "timestamp")):
        return "bright_magenta"
    if any(t in dt for t in ("array", "map", "struct")):
        return "bright_blue"
    if "binary" in dt:
        return "bright_red"
    return "white"
