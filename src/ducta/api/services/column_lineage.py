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

Column lineage for the nodes whose logic is SQL: an ingest node's query (or
its table and columns) says which source columns each output column comes
from. Python transforms are not analysed — their lineage is the code.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _sources_of(column: str, sql: str, dialect: Optional[str]) -> List[str]:
    """``schema.table.column`` for each source column *column* is computed from."""
    from sqlglot import exp
    from sqlglot.lineage import lineage

    out = set()
    for leaf in lineage(column, sql, dialect=dialect).walk():
        if list(leaf.downstream):
            continue
        col = leaf.name.split(".")[-1]
        table = leaf.expression if isinstance(leaf.expression, exp.Table) else None
        if table is not None:
            qualified = ".".join(p for p in (table.catalog, table.db, table.name) if p)
            out.add(f"{qualified}.{col}")
        else:
            out.add(leaf.name)
    return sorted(out)


def ingest_column_lineage(ingest: Dict[str, Any], dialect: Optional[str] = None) -> Dict[str, Any]:
    """``{"columns": [{"column", "sources": [...]}], "note"}`` for an ingest spec."""
    import sqlglot
    from sqlglot import exp

    source = ingest.get("source") or "source"
    query = ingest.get("query")
    if query:
        try:
            tree = sqlglot.parse_one(query, read=dialect)
        except sqlglot.errors.ParseError as e:
            return {"columns": [], "note": f"The query does not parse: {e}"}
        select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
        if select is None:
            return {"columns": [], "note": "Not a SELECT"}
        columns = []
        for projection in select.expressions:
            if isinstance(projection, exp.Star):
                return {
                    "columns": columns,
                    "note": "SELECT * — the columns are whatever the source has",
                }
            name = projection.alias_or_name
            entry: Dict[str, Any] = {"column": name, "sources": []}
            try:
                entry["sources"] = [f"{source}:{s}" for s in _sources_of(name, query, dialect)]
            except Exception as e:  # noqa: BLE001 — one column we cannot trace
                entry["error"] = str(e)
            columns.append(entry)
        return {"columns": columns, "note": None}
    table = ingest.get("table")
    if table:
        cols = ingest.get("columns") or []
        if not cols:
            return {"columns": [], "note": f"Every column of {table}"}
        return {
            "columns": [{"column": c, "sources": [f"{source}:{table}.{c}"]} for c in cols],
            "note": None,
        }
    return {"columns": [], "note": "No table or query to trace"}
