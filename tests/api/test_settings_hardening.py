"""Settings values that silently disabled safety checks when mistyped."""

from __future__ import annotations

import warnings

import pytest

from ducta.api.config import Settings


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
