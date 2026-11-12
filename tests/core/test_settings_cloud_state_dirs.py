"""Ducta's state directories stay local under a cloud output (review 2026-11-11).

The certificate, chain state and locks default to ``${output_path}/${environment}/.ducta``;
with ``s3://bucket/out`` they were written to a local folder named ``s3:``. The
default now falls back to ``.ducta/<env>/…`` with a note; a cloud directory set by
hand is a preflight error.
"""

from __future__ import annotations

from types import SimpleNamespace

from ducta.core.preflight import PreflightReport, _check_state_dirs
from ducta.core.settings import CoreSettings
from ducta.stream.journal import journal_base

CLOUD = {"output_path": "s3://bucket/out", "environment": "prod"}


def test_defaults_fall_back_to_local_with_notes():
    s = CoreSettings.from_context(CLOUD)
    assert s.run_certificate_dir == ".ducta/prod/runs"
    assert s.chain_state_dir == ".ducta/prod/chain_state"
    assert s.run_lock_dir == ".ducta/prod/locks"
    assert len(s.state_dir_notes) == 3
    assert any("guard this host only" in note for note in s.state_dir_notes)


def test_storage_lock_stays_on_object_storage():
    s = CoreSettings.from_context({**CLOUD, "run_lock": {"backend": "storage"}})
    assert s.run_lock_dir == "s3://bucket/out/prod/.ducta/locks"


def test_local_output_unchanged():
    s = CoreSettings.from_context({"output_path": "data", "environment": "dev"})
    assert s.run_certificate_dir == "data/dev/.ducta/runs"
    assert s.state_dir_notes == ()


def test_preflight_warns_on_fallback_and_refuses_explicit_cloud_dirs():
    report = PreflightReport(pipeline_name="p")
    _check_state_dirs(report, CoreSettings.from_context(CLOUD))
    assert report.ok and len(report.warnings) == 3

    explicit = CoreSettings.from_context(
        {**CLOUD, "run_certificate_dir": "s3://x/runs", "chain": {"state_dir": "gs://x/c"}}
    )
    report = PreflightReport(pipeline_name="p")
    _check_state_dirs(report, explicit)
    assert len(report.errors) == 2
    assert "run_certificate_dir" in report.errors[0]


def test_local_lock_backend_on_cloud_dir_is_refused_in_preflight():
    s = CoreSettings.from_context({**CLOUD, "run_lock": {"dir": "s3://x/locks"}})
    report = PreflightReport(pipeline_name="p")
    _check_state_dirs(report, s)
    assert any("run_lock.dir" in e for e in report.errors)


def test_stream_journal_default_stays_local():
    ctx = SimpleNamespace(global_config=dict(CLOUD), output_path=CLOUD["output_path"], env="prod")
    assert journal_base(ctx) == ".ducta/prod/streams"
    ctx.global_config["stream_journal_dir"] = "s3://x/journal"
    assert journal_base(ctx) is None  # set by hand to cloud: disabled, as before
