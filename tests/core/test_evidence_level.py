"""`evidence_level`: the project chooses how much evidence a run must leave.

off | record (default, historical behaviour) | required | signed. The legacy
`enable_run_certificate` / `require_run_certificate` keys keep working; one
that contradicts an explicit level is a preflight error, never a silent
override. The level is recorded inside the certificate so `verify` can hold a
`signed` certificate to its own policy.
"""

from __future__ import annotations

import pytest

from ducta.core.certificate import RunCertificate, verify_certificate_data
from ducta.core.settings import CoreSettings

KEY = b"a-long-random-signing-key"


def _settings(**gs) -> CoreSettings:
    return CoreSettings.from_context(gs)


class TestResolution:
    def test_default_is_record(self):
        s = _settings()
        assert (s.evidence_level, s.enable_run_certificate, s.require_run_certificate) == (
            "record",
            True,
            False,
        )
        assert s.evidence_problems == ()

    @pytest.mark.parametrize(
        "level, enable, require",
        [
            ("off", False, False),
            ("record", True, False),
            ("required", True, True),
            ("signed", True, True),
            ("SIGNED", True, True),
        ],
    )
    def test_explicit_level_drives_the_booleans(self, level, enable, require):
        s = _settings(evidence_level=level)
        assert s.enable_run_certificate is enable
        assert s.require_run_certificate is require
        assert s.evidence_problems == ()

    def test_legacy_keys_alone_still_work(self):
        assert _settings(require_run_certificate=True).evidence_level == "required"
        assert _settings(enable_run_certificate=False).evidence_level == "off"

    def test_legacy_key_contradicting_explicit_level_is_a_problem(self):
        s = _settings(evidence_level="required", require_run_certificate=False)
        assert any("contradicts" in p for p in s.evidence_problems)

    def test_legacy_key_agreeing_with_level_is_fine(self):
        assert (
            _settings(evidence_level="required", require_run_certificate=True).evidence_problems
            == ()
        )

    def test_legacy_self_contradiction_is_a_problem(self):
        s = _settings(enable_run_certificate=False, require_run_certificate=True)
        assert s.evidence_problems

    def test_unknown_level_is_a_problem_and_never_weakens(self):
        s = _settings(evidence_level="signd")
        assert s.evidence_problems
        # Falls back to the strictest level that does not need a key.
        assert s.evidence_level == "required"
        assert s.require_run_certificate is True


class TestPreflight:
    def _report(self, monkeypatch, **gs):
        from ducta.core import preflight

        monkeypatch.delenv("DUCTA_CERTIFICATE_KEY", raising=False)
        monkeypatch.delenv("Ducta_CERTIFICATE_KEY", raising=False)
        report = preflight.PreflightReport(pipeline_name="p")
        preflight._check_evidence_policy(report, {**gs})
        return report

    def test_signed_without_key_fails_preflight(self, monkeypatch):
        report = self._report(monkeypatch, evidence_level="signed")
        assert not report.ok
        assert any("DUCTA_CERTIFICATE_KEY" in e for e in report.errors)

    def test_signed_with_env_key_passes(self, monkeypatch):
        from ducta.core import preflight

        monkeypatch.setenv("DUCTA_CERTIFICATE_KEY", KEY.decode())
        report = preflight.PreflightReport(pipeline_name="p")
        preflight._check_evidence_policy(report, {"evidence_level": "signed"})
        assert report.ok

    def test_contradiction_fails_preflight(self, monkeypatch):
        report = self._report(monkeypatch, evidence_level="off", require_run_certificate=True)
        assert not report.ok

    def test_record_default_passes(self, monkeypatch):
        assert self._report(monkeypatch).ok


def _cert(evidence_level: str) -> RunCertificate:
    cert = RunCertificate(
        run_id="run-1",
        pipeline="p",
        environment_name="dev",
        status="success",
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:01:00+00:00",
        ducta_version="test",
        evidence_level=evidence_level,
    )
    cert.certificate_hash = cert.compute_hash()
    return cert


class TestVerifyHoldsTheCertificateToItsPolicy:
    def test_level_is_inside_the_hash(self):
        assert _cert("record").compute_hash() != _cert("signed").compute_hash()

    def test_relaxing_the_recorded_level_is_detected(self):
        data = _cert("signed").sealed()
        data["evidence_level"] = "record"
        assert verify_certificate_data(data).ok is False

    def test_signed_policy_but_unsigned_certificate_fails(self):
        result = verify_certificate_data(_cert("signed").sealed())
        assert result.ok is False
        assert "evidence_level=signed" in result.reason

    def test_signed_policy_without_key_is_integrity_only_and_policy_unmet(self):
        cert = _cert("signed")
        cert.sign(KEY)
        result = verify_certificate_data(cert.sealed())
        assert result.ok is True
        assert result.level == "integrity"
        assert result.policy_satisfied is False

    def test_signed_policy_with_key_is_authenticated(self):
        cert = _cert("signed")
        cert.sign(KEY)
        result = verify_certificate_data(cert.sealed(), signing_key=KEY)
        assert result.ok is True
        assert result.level == "authenticated"
        assert result.policy_satisfied is True

    def test_record_policy_without_key_meets_its_policy(self):
        result = verify_certificate_data(_cert("record").sealed())
        assert result.ok is True
        assert result.policy_satisfied is True


def test_canonical_env_var_wins_over_legacy(monkeypatch):
    from ducta.core.certificate import resolve_signing_key

    monkeypatch.setenv("DUCTA_CERTIFICATE_KEY", "canonical")
    monkeypatch.setenv("Ducta_CERTIFICATE_KEY", "legacy")
    assert resolve_signing_key({}) == b"canonical"
