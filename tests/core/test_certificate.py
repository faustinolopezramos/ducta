"""Unit tests for ducta.core.certificate — tamper-evident Run Certificates."""

from __future__ import annotations

import json

from ducta.core.certificate import (
    RunCertificate,
    load_certificate,
    resolve_signing_key,
    resolve_signing_key_from_dir,
    verify_certificate,
    write_certificate,
)


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


class TestHashing:
    def test_hash_is_deterministic(self):
        assert _make_cert().compute_hash() == _make_cert().compute_hash()

    def test_hash_prefixed(self):
        assert _make_cert().compute_hash().startswith("sha256:")

    def test_hash_changes_with_content(self):
        assert (
            _make_cert(status="success").compute_hash()
            != _make_cert(status="failed").compute_hash()
        )

    def test_sealed_contains_hash(self):
        sealed = _make_cert().sealed()
        assert sealed["certificate_hash"].startswith("sha256:")
        assert "signature" not in sealed  # unsigned by default


class TestWriteVerifyRoundtrip:
    def test_untampered_verifies_ok(self, tmp_path):
        path = write_certificate(_make_cert(), tmp_path)
        result = verify_certificate(path)
        assert result.ok is True
        assert result.run_id == "run-1"
        assert result.signature == "unsigned"

    def test_tampered_file_detected(self, tmp_path):
        path = write_certificate(_make_cert(), tmp_path)
        data = load_certificate(path)
        data["status"] = "failed"  # tamper without recomputing hash
        path.write_text(json.dumps(data), encoding="utf-8")
        result = verify_certificate(path)
        assert result.ok is False
        assert "hash mismatch" in result.reason


class TestSigning:
    KEY = b"super-secret-signing-key"

    def test_sign_adds_signature(self):
        cert = _make_cert()
        cert.sign(self.KEY)
        sealed = cert.sealed()
        assert sealed["signature"].startswith("hmac-sha256:")
        assert sealed["key_id"]

    def test_valid_signature_verifies(self, tmp_path):
        cert = _make_cert()
        cert.sign(self.KEY)
        path = write_certificate(cert, tmp_path)
        result = verify_certificate(path, signing_key=self.KEY)
        assert result.ok is True
        assert result.signature == "valid"

    def test_wrong_key_fails(self, tmp_path):
        cert = _make_cert()
        cert.sign(self.KEY)
        path = write_certificate(cert, tmp_path)
        result = verify_certificate(path, signing_key=b"wrong-key")
        assert result.ok is False
        assert result.signature == "invalid"

    def test_signed_without_key_is_untampered_but_unverified(self, tmp_path):
        cert = _make_cert()
        cert.sign(self.KEY)
        path = write_certificate(cert, tmp_path)
        result = verify_certificate(path)  # no key provided
        assert result.ok is True
        assert result.signature == "present (no key)"


class TestResolveSigningKey:
    def test_env_var_upper_case_is_accepted(self, monkeypatch):
        monkeypatch.delenv("Ducta_CERTIFICATE_KEY", raising=False)
        monkeypatch.setenv("DUCTA_CERTIFICATE_KEY", "upper-case-key")
        assert resolve_signing_key({}) == b"upper-case-key"

    def test_mixed_case_env_var_still_works(self, monkeypatch):
        monkeypatch.setenv("Ducta_CERTIFICATE_KEY", "mixed-case-key")
        monkeypatch.delenv("DUCTA_CERTIFICATE_KEY", raising=False)
        assert resolve_signing_key({}) == b"mixed-case-key"

    def test_no_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("Ducta_CERTIFICATE_KEY", raising=False)
        monkeypatch.delenv("DUCTA_CERTIFICATE_KEY", raising=False)
        assert resolve_signing_key({}) is None

    def test_config_key_used_when_no_env_var(self, monkeypatch):
        monkeypatch.delenv("Ducta_CERTIFICATE_KEY", raising=False)
        monkeypatch.delenv("DUCTA_CERTIFICATE_KEY", raising=False)
        ctx = {"certificate_signing_key": "from-config"}
        assert resolve_signing_key(ctx) == b"from-config"


class TestResolveSigningKeyFromDir:
    def test_reads_key_from_global_settings_yaml(self, tmp_path, monkeypatch):
        monkeypatch.delenv("Ducta_CERTIFICATE_KEY", raising=False)
        monkeypatch.delenv("DUCTA_CERTIFICATE_KEY", raising=False)
        (tmp_path / "global_settings.yaml").write_text("certificate_signing_key: dir-based-key\n")
        assert resolve_signing_key_from_dir(tmp_path) == b"dir-based-key"

    def test_falls_back_to_env_var_when_no_config_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("Ducta_CERTIFICATE_KEY", "env-fallback-key")
        assert resolve_signing_key_from_dir(tmp_path) == b"env-fallback-key"

    def test_reads_key_from_global_settings_under_config_subdir(self, tmp_path, monkeypatch):
        """Regression: a project keeping global_settings.* under config/ (a
        layout `setting/config_forms.py`'s `_dir_convention_paths` already
        supports) used to be invisible to `certify verify` — only the
        project root itself was searched."""
        monkeypatch.delenv("Ducta_CERTIFICATE_KEY", raising=False)
        monkeypatch.delenv("DUCTA_CERTIFICATE_KEY", raising=False)
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "global_settings.yaml").write_text(
            "certificate_signing_key: config-subdir-key\n"
        )
        assert resolve_signing_key_from_dir(tmp_path) == b"config-subdir-key"

    def test_prefers_root_over_config_subdir_when_both_exist(self, tmp_path, monkeypatch):
        monkeypatch.delenv("Ducta_CERTIFICATE_KEY", raising=False)
        monkeypatch.delenv("DUCTA_CERTIFICATE_KEY", raising=False)
        (tmp_path / "global_settings.yaml").write_text("certificate_signing_key: root-key\n")
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "global_settings.yaml").write_text(
            "certificate_signing_key: config-subdir-key\n"
        )
        assert resolve_signing_key_from_dir(tmp_path) == b"root-key"
