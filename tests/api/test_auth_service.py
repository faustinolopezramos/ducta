"""Unit tests for ducta.api.auth.service.AuthService (bcrypt + JWT)."""

from __future__ import annotations

import jwt
import pytest

from ducta.api.auth.service import AuthService
from ducta.api.exceptions import ExpiredTokenError, InvalidTokenError

SECRET = "unit-test-secret-key"


@pytest.fixture
def svc():
    return AuthService(secret_key=SECRET)


class TestPasswords:
    def test_hash_and_verify(self, svc):
        h = svc.hash_password("s3cr3t")
        assert svc.verify_password("s3cr3t", h) is True
        assert svc.verify_password("wrong", h) is False

    def test_hash_is_salted(self, svc):
        assert svc.hash_password("x") != svc.hash_password("x")

    def test_long_password_truncated_at_72_bytes(self, svc):
        # bcrypt only considers the first 72 bytes; both must verify equal.
        h = svc.hash_password("a" * 72 + "X")
        assert svc.verify_password("a" * 72 + "Y", h) is True


class TestTokens:
    def test_roundtrip(self, svc):
        token = svc.create_access_token("uid-1", "alice", ["admin"])
        payload = svc.decode_access_token(token)
        assert payload["sub"] == "uid-1"
        assert payload["username"] == "alice"
        assert payload["roles"] == ["admin"]
        assert payload["type"] == "access"

    def test_invalid_token_raises(self, svc):
        with pytest.raises(InvalidTokenError):
            svc.decode_access_token("not.a.jwt")

    def test_wrong_secret_raises(self, svc):
        forged = jwt.encode({"sub": "x", "type": "access"}, "other-secret", algorithm="HS256")
        with pytest.raises(InvalidTokenError):
            svc.decode_access_token(forged)

    def test_wrong_token_type_rejected(self, svc):
        refresh = jwt.encode({"sub": "x", "type": "refresh"}, SECRET, algorithm="HS256")
        with pytest.raises(InvalidTokenError, match="token type"):
            svc.decode_access_token(refresh)

    def test_expired_token_raises(self):
        # negative TTL -> exp in the past
        svc = AuthService(secret_key=SECRET, access_token_expires_hours=-1)
        token = svc.create_access_token("uid", "user", [])
        with pytest.raises(ExpiredTokenError):
            svc.decode_access_token(token)

    def test_lifetime_seconds(self, svc):
        assert svc.access_token_lifetime_seconds == 24 * 3600


class TestTokenRevocation:
    """Regression: no way existed to invalidate a JWT before its own
    expiry — logout only cleared the client's cookie, so a captured/leaked
    token kept working for its full lifetime regardless of logout."""

    def test_revoked_token_is_rejected(self, svc):
        from datetime import datetime, timedelta, timezone

        token = svc.create_access_token("uid-1", "alice", ["admin"])
        payload = svc.decode_access_token(token)  # still valid before revocation

        svc.revoke_token(payload["jti"], datetime.now(tz=timezone.utc) + timedelta(hours=1))

        with pytest.raises(InvalidTokenError, match="revoked"):
            svc.decode_access_token(token)

    def test_unrevoked_token_still_works(self, svc):
        token = svc.create_access_token("uid-1", "alice", ["admin"])
        assert svc.decode_access_token(token)["sub"] == "uid-1"

    def test_revoking_one_token_does_not_affect_another(self, svc):
        from datetime import datetime, timedelta, timezone

        token_a = svc.create_access_token("uid-1", "alice", [])
        token_b = svc.create_access_token("uid-1", "alice", [])
        payload_a = svc.decode_access_token(token_a)

        svc.revoke_token(payload_a["jti"], datetime.now(tz=timezone.utc) + timedelta(hours=1))

        with pytest.raises(InvalidTokenError):
            svc.decode_access_token(token_a)
        assert svc.decode_access_token(token_b)["sub"] == "uid-1"

    def test_expired_revocation_entries_are_pruned(self, svc):
        from datetime import datetime, timedelta, timezone

        # A revocation whose own expiry has already passed must not linger
        # forever in memory — pruned on the next revoke_token call.
        svc.revoke_token("stale-jti", datetime.now(tz=timezone.utc) - timedelta(hours=1))
        svc.revoke_token("new-jti", datetime.now(tz=timezone.utc) + timedelta(hours=1))

        assert "stale-jti" not in svc._revoked
        assert "new-jti" in svc._revoked
