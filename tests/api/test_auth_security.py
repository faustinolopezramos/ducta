"""Shared security-critical logic used by both `auth.users.UserStore` and
`db.stores.user_store.DatabaseUserStore` — extracted to `auth.security` so
the admin-password production rule and the constant-time auth probe can't
silently drift between the two stores."""

from __future__ import annotations

import pytest

from ducta.api.auth.security import probe_or_verify, resolve_admin_password


class TestResolveAdminPassword:
    def test_missing_password_in_production_raises(self):
        with pytest.raises(RuntimeError, match="must be set in production"):
            resolve_admin_password(None, is_production=True)

    def test_insecure_default_password_in_production_raises(self):
        with pytest.raises(RuntimeError, match="insecure default value"):
            resolve_admin_password("admin", is_production=True)

    def test_missing_password_outside_production_defaults_to_admin(self):
        assert resolve_admin_password(None, is_production=False) == "admin"

    def test_explicit_password_outside_production_is_used_as_is(self):
        assert resolve_admin_password("s3cr3t", is_production=False) == "s3cr3t"

    def test_explicit_strong_password_in_production_is_accepted(self):
        assert resolve_admin_password("s3cr3t", is_production=True) == "s3cr3t"


class TestProbeOrVerify:
    def test_unknown_username_returns_false(self):
        calls = []
        result = probe_or_verify(
            username_found=False,
            password="whatever",
            stored_hash=None,
            dummy_hash="dummy-hash",
            verify_fn=lambda plain, hashed: calls.append((plain, hashed)) or True,
        )
        assert result is False

    def test_unknown_username_still_invokes_verify_fn_for_constant_time(self):
        """The whole point of the probe: a nonexistent username must not
        short-circuit faster than a wrong password would."""
        calls = []
        probe_or_verify(
            username_found=False,
            password="whatever",
            stored_hash=None,
            dummy_hash="dummy-hash",
            verify_fn=lambda plain, hashed: calls.append((plain, hashed)) or False,
        )
        assert calls == [("__dummy_probe__", "dummy-hash")]

    def test_known_username_delegates_to_verify_fn_against_real_hash(self):
        calls = []

        def verify_fn(plain, hashed):
            calls.append((plain, hashed))
            return plain == "correct" and hashed == "real-hash"

        assert (
            probe_or_verify(
                username_found=True,
                password="correct",
                stored_hash="real-hash",
                dummy_hash="dummy-hash",
                verify_fn=verify_fn,
            )
            is True
        )
        assert calls == [("correct", "real-hash")]

    def test_known_username_wrong_password_returns_false(self):
        result = probe_or_verify(
            username_found=True,
            password="wrong",
            stored_hash="real-hash",
            dummy_hash="dummy-hash",
            verify_fn=lambda plain, hashed: plain == "correct",
        )
        assert result is False
