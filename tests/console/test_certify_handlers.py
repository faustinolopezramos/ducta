"""`ducta certify list | show | verify | diff` against real certificates.

The certificates are built and sealed with the same API a pipeline run uses
(`RunCertificate` + `write_certificate`), so hashing, signing and verification
are the real ones; only the pipeline run itself is skipped.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from rich.console import Console

from ducta.console.commands import certify_cmds
from ducta.console.core import ExitCode
from ducta.core.certificate import RunCertificate, write_certificate

KEY = b"test-signing-key"


def _certificate(run_id: str, *, status: str = "success", started: str, fingerprint: str):
    return RunCertificate(
        run_id=run_id,
        pipeline="etl",
        environment_name="dev",
        status=status,
        started_at=started,
        ended_at=started,
        ducta_version="0.0-test",
        duration_seconds=1.5,
        config_fingerprint="cfg-1",
        nodes=[{"name": "clean", "status": status}],
        # The shape DataFingerprint.to_dict() writes: diff compares content_hash.
        outputs={
            "silver.orders": {
                "fingerprint": fingerprint,
                "algorithm": "xxhash64-multiset/v2",
                "engine": "pandas",
                "mode": "exact",
                "schema_hash": "s1",
                "row_count": 3,
                "content_hash": fingerprint,
            }
        },
        quality=[{"dataset": "silver.orders", "passed": True, "score": 1.0}],
    )


@pytest.fixture
def runs(tmp_path, monkeypatch):
    """A runs directory with two signed certificates, and a recording console."""
    runs_dir = tmp_path / "runs"
    first = _certificate("aaaa1111", started="2026-10-01T10:00:00+00:00", fingerprint="f1")
    second = _certificate("bbbb2222", started="2026-10-02T10:00:00+00:00", fingerprint="f2")
    for cert in (first, second):
        cert.sign(KEY)
        write_certificate(cert, runs_dir / cert.run_id)

    console = Console(record=True, width=160)
    monkeypatch.setattr(certify_cmds, "get_console", lambda: console)
    monkeypatch.chdir(tmp_path)  # no project here: --dir is the only source
    monkeypatch.setenv("DUCTA_CERTIFICATE_KEY", KEY.decode())
    return SimpleNamespace(dir=runs_dir, console=console)


def _args(runs, command, **extra):
    base = {"certify_command": command, "dir": str(runs.dir), "env": None, "base_path": None}
    return SimpleNamespace(**{**base, **extra})


def test_list_shows_every_run_newest_first(runs):
    assert certify_cmds.handle_certify(_args(runs, "list")) == ExitCode.SUCCESS.value

    text = runs.console.export_text()
    assert "aaaa1111" in text and "bbbb2222" in text
    assert text.index("bbbb2222") < text.index("aaaa1111")


def test_list_of_an_empty_directory_is_not_an_error(runs, tmp_path):
    args = _args(runs, "list", dir=str(tmp_path / "nothing"))
    assert certify_cmds.handle_certify(args) == ExitCode.SUCCESS.value


def test_show_prints_the_certificate(runs):
    assert certify_cmds.handle_certify(_args(runs, "show", run_id="aaaa")) == 0
    assert "etl" in runs.console.export_text()


def test_show_json_is_the_raw_certificate(runs, capsys):
    assert certify_cmds.handle_certify(_args(runs, "show", run_id="aaaa1111", json=True)) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["run_id"] == "aaaa1111" and data["certificate_hash"]


def test_show_an_unknown_run_is_a_validation_error(runs):
    code = certify_cmds.handle_certify(_args(runs, "show", run_id="zzzz"))
    assert code == ExitCode.VALIDATION_ERROR.value


def test_an_ambiguous_prefix_matches_nothing(runs):
    other = _certificate("aaaa9999", started="2026-10-03T10:00:00+00:00", fingerprint="f3")
    write_certificate(other, runs.dir / other.run_id)
    code = certify_cmds.handle_certify(_args(runs, "show", run_id="aaaa"))
    assert code == ExitCode.VALIDATION_ERROR.value


def test_verify_accepts_an_untouched_signed_certificate(runs):
    code = certify_cmds.handle_certify(_args(runs, "verify", run_id="aaaa1111", reproduce=False))
    assert code == ExitCode.SUCCESS.value


def test_verify_rejects_a_tampered_certificate(runs):
    path = runs.dir / "aaaa1111" / "certificate.json"
    data = json.loads(path.read_text())
    data["status"] = "failed"  # edited after sealing
    path.write_text(json.dumps(data))

    code = certify_cmds.handle_certify(_args(runs, "verify", run_id="aaaa1111", reproduce=False))
    assert code == ExitCode.VALIDATION_ERROR.value


def test_verify_rejects_a_certificate_signed_with_another_key(runs, monkeypatch):
    monkeypatch.setenv("DUCTA_CERTIFICATE_KEY", "a-different-key")
    code = certify_cmds.handle_certify(_args(runs, "verify", run_id="aaaa1111", reproduce=False))
    assert code == ExitCode.VALIDATION_ERROR.value


def test_diff_reports_the_changed_output(runs):
    args = _args(runs, "diff", run_a="aaaa1111", run_b="bbbb2222")
    assert certify_cmds.handle_certify(args) == ExitCode.SUCCESS.value

    text = runs.console.export_text()
    assert "silver.orders" in text
    assert "DIFFERENT" in text  # f1 vs f2
    assert "Config fingerprint match: same" in text


def test_diff_with_an_unknown_run_is_a_validation_error(runs):
    args = _args(runs, "diff", run_a="aaaa1111", run_b="nope")
    assert certify_cmds.handle_certify(args) == ExitCode.VALIDATION_ERROR.value


def test_an_unknown_subcommand_is_a_general_error(runs):
    assert certify_cmds.handle_certify(_args(runs, "explode")) == ExitCode.GENERAL_ERROR.value


@pytest.mark.parametrize(
    "seconds_ago, label",
    [(5, "just now"), (120, "2m ago"), (7200, "2h ago"), (3 * 86400, "3d ago")],
)
def test_relative_time(seconds_ago, label):
    from datetime import datetime, timedelta, timezone

    stamp = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()
    assert certify_cmds._relative_time(stamp) == label


def test_relative_time_falls_back_to_what_it_cannot_read():
    assert certify_cmds._relative_time(None) == "?"
    assert certify_cmds._relative_time("yesterday") == "yesterday"
    assert certify_cmds._relative_time("2999-01-01T00:00:00+00:00").startswith("2999")


def test_fingerprint_label_names_degraded_modes():
    assert "exact" in certify_cmds._fingerprint_label({"mode": "exact"})
    sample = {"mode": "sample", "details": {"sample_rows_covered": 100}}
    assert "sample (100 rows)" in certify_cmds._fingerprint_label(sample)
    assert "schema-only" in certify_cmds._fingerprint_label({"mode": "schema"})
    assert "?" in certify_cmds._fingerprint_label({})


def test_quality_summary_label():
    assert certify_cmds._quality_summary_label([]) == "—"
    assert "2/2 passed" in certify_cmds._quality_summary_label([{"passed": True}] * 2)
    mixed = [{"passed": True}, {"passed": False}]
    assert "1/2 passed" in certify_cmds._quality_summary_label(mixed)
