"""Column lineage of ingest nodes, from their SQL."""

from __future__ import annotations

from ducta.api.services.column_lineage import ingest_column_lineage


def test_query_columns_trace_to_their_source_columns():
    q = (
        "SELECT s.id AS student_id, UPPER(s.name) AS name, c.amount + c.fee AS total_cost "
        "FROM dbo.students s JOIN dbo.costs c ON c.student_id = s.id"
    )
    out = {
        c["column"]: c["sources"]
        for c in ingest_column_lineage({"source": "crm", "query": q}, "tsql")["columns"]
    }
    assert out == {
        "student_id": ["crm:dbo.students.id"],
        "name": ["crm:dbo.students.name"],
        "total_cost": ["crm:dbo.costs.amount", "crm:dbo.costs.fee"],
    }


def test_table_and_columns_map_one_to_one_and_star_says_so():
    out = ingest_column_lineage({"source": "crm", "table": "dbo.t", "columns": ["a"]})
    assert out["columns"] == [{"column": "a", "sources": ["crm:dbo.t.a"]}]
    assert "SELECT *" in ingest_column_lineage({"query": "SELECT * FROM t"})["note"]
    assert "does not parse" in ingest_column_lineage({"query": "SELEC oops FROM"})["note"]
