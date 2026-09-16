"""Tests for the standalone (project-less, unauthenticated) certificate verify endpoint.

Unlike the rest of `routes/certificates.py`, this endpoint takes a certificate
the caller already has — pasted or uploaded — rather than one this instance
already knows about, and carries no `Depends(require_permission(...))`. These
tests build a minimal app around just that router (same pattern as
`test_cors.py`) instead of standing up the whole workspace-backed API.
"""

from __future__ import annotations

import json

import pytest

fastapi = pytest.importorskip(
    "fastapi", reason="standalone certificate tests require the api extra"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ducta.api.routes.certificates_standalone import router  # noqa: E402
from ducta.core.certificate import RunCertificate  # noqa: E402


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


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


class TestStandaloneVerify:
    def test_untampered_unsigned_certificate_verifies_ok(self, client: TestClient):
        cert = _make_cert()
        resp = client.post(
            "/api/certificates/verify",
            json={"certificate_json": json.dumps(cert.sealed())},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["signature"] == "unsigned"
        assert body["run_id"] == "run-1"

    def test_valid_signature_with_correct_key(self, client: TestClient):
        cert = _make_cert()
        cert.sign(b"top-secret")
        resp = client.post(
            "/api/certificates/verify",
            json={"certificate_json": json.dumps(cert.sealed()), "signing_key": "top-secret"},
        )
        body = resp.json()
        assert resp.status_code == 200
        assert body["ok"] is True
        assert body["signature"] == "valid"

    def test_signed_but_no_key_supplied(self, client: TestClient):
        cert = _make_cert()
        cert.sign(b"top-secret")
        resp = client.post(
            "/api/certificates/verify",
            json={"certificate_json": json.dumps(cert.sealed())},
        )
        body = resp.json()
        assert body["ok"] is True
        assert body["signature"] == "present (no key)"

    def test_wrong_key_fails(self, client: TestClient):
        cert = _make_cert()
        cert.sign(b"top-secret")
        resp = client.post(
            "/api/certificates/verify",
            json={"certificate_json": json.dumps(cert.sealed()), "signing_key": "wrong-key"},
        )
        body = resp.json()
        assert body["ok"] is False
        assert body["signature"] == "invalid"

    def test_hand_edited_certificate_fails_hash_check(self, client: TestClient):
        cert = _make_cert()
        sealed = cert.sealed()
        sealed["status"] = "failed"  # tampered after the hash was computed
        resp = client.post(
            "/api/certificates/verify",
            json={"certificate_json": json.dumps(sealed)},
        )
        body = resp.json()
        assert body["ok"] is False
        assert "hash mismatch" in body["reason"]

    def test_stripped_signature_is_caught(self, client: TestClient):
        cert = _make_cert()
        cert.sign(b"top-secret")
        sealed = cert.sealed()
        del sealed["signature"]  # forgery attempt: claim signed=true, strip the signature
        resp = client.post(
            "/api/certificates/verify",
            json={"certificate_json": json.dumps(sealed)},
        )
        body = resp.json()
        assert body["ok"] is False
        assert body["signature"] == "stripped"

    def test_invalid_json_is_rejected_cleanly(self, client: TestClient):
        resp = client.post(
            "/api/certificates/verify",
            json={"certificate_json": "{not valid json"},
        )
        assert resp.status_code == 422

    def test_json_that_is_not_an_object_is_rejected(self, client: TestClient):
        resp = client.post(
            "/api/certificates/verify",
            json={"certificate_json": json.dumps([1, 2, 3])},
        )
        assert resp.status_code == 422

    def test_no_auth_dependency_is_declared(self):
        """The whole point is reachability without an account on this instance."""
        route = next(r for r in router.routes if r.path == "/certificates/verify")
        assert route.dependencies == []
