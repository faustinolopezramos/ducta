"""The certificate's ``code`` block: what logic a run actually executed.

``config_fingerprint`` covers the config documents, which *name* a
transformation (``module``/``function``) without committing to its text. These
tests pin the property that closes that gap: change the code, change the
certificate.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from ducta.core.certificate import (
    SCHEMA_VERSION,
    RunCertificate,
    build_certificate,
    load_certificate,
    verify_certificate,
    write_certificate,
)
from ducta.core.code_fingerprint import clear_cache, fingerprint_callable
from ducta.core.ledger import ledger_for


def _make_cert(**overrides) -> RunCertificate:
    base = dict(
        run_id="run-1",
        pipeline="sales_daily",
        environment_name="dev",
        status="success",
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:01:00+00:00",
        ducta_version="1.0.0",
    )
    base.update(overrides)
    cert = RunCertificate(**base)
    cert.certificate_hash = cert.compute_hash()
    return cert


class TestCodeIsInsideTheHash:
    def test_schema_version_advertises_the_new_block(self):
        # The code block arrived in 1.5; later versions keep it.
        assert tuple(int(p) for p in SCHEMA_VERSION.split(".")) >= (1, 5)
        assert "code" in _make_cert().content()

    def test_a_different_code_hash_changes_the_certificate_hash(self):
        """The whole point: two runs over the same data but different logic
        must not produce the same certificate."""
        a = _make_cert(code={"nodes": {"clean": {"source_hash": "sha256:aaa"}}})
        b = _make_cert(code={"nodes": {"clean": {"source_hash": "sha256:bbb"}}})

        assert a.compute_hash() != b.compute_hash()

    def test_stripping_the_code_block_fails_verification(self, tmp_path):
        path = write_certificate(
            _make_cert(code={"nodes": {"clean": {"source_hash": "sha256:aaa"}}}), tmp_path
        )
        data = load_certificate(path)
        del data["code"]
        path.write_text(json.dumps(data), encoding="utf-8")

        assert verify_certificate(path).ok is False

    def test_roundtrip_still_verifies(self, tmp_path):
        cert = _make_cert(code={"nodes": {"clean": {"source_hash": "sha256:aaa"}}})
        assert verify_certificate(write_certificate(cert, tmp_path)).ok is True


class TestOlderCertificatesStillVerify:
    def test_a_pre_1_4_certificate_verifies_unchanged(self, tmp_path):
        """The hash is recomputed over whatever keys the file carries, so a
        certificate written before `code` existed must not start failing."""
        cert = _make_cert()
        sealed = cert.sealed()
        del sealed["code"]
        sealed["schema_version"] = "1.3"
        # Re-seal exactly as a 1.3 writer would have.
        import hashlib

        content = {k: v for k, v in sealed.items() if k != "certificate_hash"}
        sealed["certificate_hash"] = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode()
            ).hexdigest()
        )

        path = tmp_path / "certificate.json"
        path.write_text(json.dumps(sealed), encoding="utf-8")

        assert verify_certificate(path).ok is True


def _transform(df):
    return df


class TestBuildFromLedger:
    def test_build_certificate_carries_the_recorded_code(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        clear_cache()
        context = SimpleNamespace(
            global_config={},
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
        )
        ledger = ledger_for(context)
        ledger.record_code("clean_sales", fingerprint_callable(_transform))

        now = datetime.now(timezone.utc)
        cert = build_certificate(
            context,
            run_id="r1",
            pipeline="p",
            environment_name="dev",
            status="success",
            started_at=now,
            ended_at=now,
            ducta_version="0.1.1",
        )

        assert cert.code["nodes"]["clean_sales"]["source_hash"].startswith("sha256:")

    def test_quality_extensions_are_hashed_from_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        context = SimpleNamespace(
            global_config={"quality": {"extensions": ["ducta.core.code_fingerprint"]}},
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
        )
        now = datetime.now(timezone.utc)
        cert = build_certificate(
            context,
            run_id="r1",
            pipeline="p",
            environment_name="dev",
            status="success",
            started_at=now,
            ended_at=now,
            ducta_version="0.1.1",
        )

        ext = cert.code["quality_extensions"]["ducta.core.code_fingerprint"]
        assert ext["module_hash"].startswith("sha256:")

    def test_no_extensions_configured_leaves_the_key_out(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        context = SimpleNamespace(
            global_config={},
            pipelines_config={},
            nodes_config={},
            input_config={},
            output_config={},
        )
        now = datetime.now(timezone.utc)
        cert = build_certificate(
            context,
            run_id="r1",
            pipeline="p",
            environment_name="dev",
            status="success",
            started_at=now,
            ended_at=now,
            ducta_version="0.1.1",
        )

        assert "quality_extensions" not in cert.code
