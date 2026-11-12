"""Credentials in a node error are masked in what outlives the run (review 2026-11-11).

A driver error echoing ``password=…`` or ``user:pw@host`` went verbatim into the run
certificate (node and run ``error``), the run result and the terminal; only the log
file was redacted.
"""

from __future__ import annotations

from ducta.ai.context import redact
from ducta.core.ledger import ledger_for
from ducta.core.results import PipelineRunResult
from ducta.redaction import redact_text
from tests.core.fakes import FakeContext

LEAK = "password=hunter2 jdbc:postgresql://u:secretpw@db/x failed"


def _clean(text: str) -> None:
    assert "hunter2" not in text and "secretpw" not in text
    assert "***" in text


def test_ledger_node_error_is_masked():
    ledger = ledger_for(FakeContext())
    ledger.record_node(name="n", status="failed", error=LEAK)
    _clean(ledger.node_details[-1]["error"])


def test_run_result_error_is_masked():
    result = PipelineRunResult(pipeline="p").add_error(LEAK)
    _clean(result.errors[0])


def test_redact_text_leaves_non_strings_and_plain_text():
    assert redact_text(None) is None
    assert redact_text("node failed: division by zero") == "node failed: division by zero"
    _clean(redact_text(LEAK))


def test_spark_conf_listing_is_masked():
    assert redact("spark.hadoop.fs.s3a.secret.key wJalrXUtnFEMIK7MDENG") == (
        "spark.hadoop.fs.s3a.secret.key ***"
    )
    # Not a credential name: untouched.
    assert redact("the partition.key column") == "the partition.key column"
    assert redact("spark.sql.shuffle.partitions 200") == "spark.sql.shuffle.partitions 200"


def test_error_box_masks_the_message():
    from io import StringIO

    from rich.console import Console

    from ducta.console.ux.error_analyzer import format_error_for_developer

    out = StringIO()
    format_error_for_developer(RuntimeError(LEAK), "n", Console(file=out, width=200))
    _clean(out.getvalue())


def test_certificate_error_is_masked():
    from datetime import datetime, timezone

    from ducta.core.certificate import build_certificate

    now = datetime.now(timezone.utc)
    cert = build_certificate(
        FakeContext(),
        run_id="r1",
        pipeline="p",
        environment_name="test",
        status="failed",
        started_at=now,
        ended_at=now,
        ducta_version="test",
        error=LEAK,
    )
    _clean(cert.error or "")
