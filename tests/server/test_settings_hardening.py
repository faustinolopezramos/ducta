"""Settings values that silently disabled safety checks when mistyped."""

from __future__ import annotations

import warnings

import pytest

from ducta_server.config import Settings


def _settings(**kwargs) -> Settings:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Settings(_env_file=None, **kwargs)


class TestEnvironmentIsConstrained:
    """`is_production()` compares with `== "production"`, so every production
    guard is keyed to that exact spelling. An unrecognised value used to land in
    the non-production branch without complaint — which is how `ENVIRONMENT=prod`
    produced a server running with `jwt_secret_key="change-me-in-production"`,
    `auth_enabled=False` and `debug` permitted."""

    @pytest.mark.parametrize("value", ["prod", "produccion", "prd", "live", ""])
    def test_unrecognised_values_are_rejected(self, value):
        with pytest.raises(Exception):
            _settings(environment=value)

    @pytest.mark.parametrize("value", ["Production", "PRODUCTION", "  production  "])
    def test_case_and_whitespace_are_folded_not_rejected(self, value):
        s = _settings(environment=value, jwt_secret_key="x" * 40, auth_enabled=True)
        assert s.environment == "production"
        assert s.is_production()

    @pytest.mark.parametrize("value", ["development", "staging", "production"])
    def test_the_three_known_values_are_accepted(self, value):
        kwargs = {"jwt_secret_key": "x" * 40, "auth_enabled": True} if value == "production" else {}
        assert _settings(environment=value, **kwargs).environment == value

    def test_a_mistyped_production_can_no_longer_skip_the_secret_check(self):
        """The guard that `ENVIRONMENT=prod` used to slip past."""
        with pytest.raises(Exception):
            _settings(environment="prod", jwt_secret_key="change-me-in-production")


class TestJwtAlgorithmIsConstrained:
    """`jwt_secret_key` is a shared secret, so only the HMAC family can sign with
    it. An unconstrained value was accepted at startup and only failed later, as
    a 500 from the first login attempt."""

    @pytest.mark.parametrize("alg", ["HS256", "HS384", "HS512"])
    def test_hmac_algorithms_are_accepted(self, alg):
        assert _settings(jwt_algorithm=alg).jwt_algorithm == alg

    @pytest.mark.parametrize("alg", ["none", "NONE", "RS256", "ES256", "nonsense"])
    def test_everything_else_fails_at_startup_not_at_first_login(self, alg):
        with pytest.raises(Exception):
            _settings(jwt_algorithm=alg)


class TestBlankJwtSecretIsUnset:
    """`JWT_SECRET_KEY=` (an empty line in .env) passed every check — only the shipped
    default was refused — and the server started with logins that always failed,
    because PyJWT refuses to sign with an empty key."""

    @pytest.mark.parametrize("value", ["", "   "])
    def test_production_refuses_a_blank_key_like_the_default(self, value):
        with pytest.raises(Exception, match="jwt_secret_key must be overridden"):
            _settings(environment="production", auth_enabled=True, jwt_secret_key=value)

    def test_an_exposed_server_with_accounts_reports_it_as_the_default(self):
        from ducta_server.config import default_credentials

        s = _settings(auth_enabled=True, host="0.0.0.0", jwt_secret_key="")
        assert any("JWT_SECRET_KEY is the default" in f for f in default_credentials(s))

    def test_a_real_key_is_kept(self):
        assert _settings(jwt_secret_key="k" * 40).jwt_secret_key == "k" * 40
