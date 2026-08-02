"""Unit tests for ducta.api.config.Settings production guards."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from ducta.api.config import Settings


class TestProductionGuards:
    def test_default_secret_in_production_rejected(self):
        with pytest.raises(PydanticValidationError, match="jwt_secret_key"):
            Settings(
                environment="production",
                jwt_secret_key="change-me-in-production",
                auth_enabled=True,
            )

    def test_auth_disabled_in_production_rejected(self):
        with pytest.raises(PydanticValidationError, match="auth_enabled"):
            Settings(
                environment="production",
                jwt_secret_key="a-strong-secret",
                auth_enabled=False,
            )

    def test_valid_production_settings(self):
        s = Settings(
            environment="production",
            jwt_secret_key="a-strong-secret",
            auth_enabled=True,
        )
        assert s.is_production() is True

    def test_development_defaults_ok(self):
        s = Settings(environment="development")
        assert s.is_development() is True
        assert s.auth_enabled is False


class TestAuthRateLimitCoupling:
    """Regression: auth_enabled=True used to leave rate limiting fully
    independent (default off), so login/other authenticated routes had no
    protection against brute-force/credential-stuffing unless an operator
    separately remembered to also set RATE_LIMIT_ENABLED=true."""

    def test_auth_enabled_auto_enables_rate_limit_by_default(self):
        s = Settings(auth_enabled=True)
        assert s.rate_limit_enabled is True

    def test_explicit_rate_limit_disabled_is_respected(self):
        s = Settings(auth_enabled=True, rate_limit_enabled=False)
        assert s.rate_limit_enabled is False

    def test_auth_disabled_does_not_force_rate_limit(self):
        s = Settings(auth_enabled=False)
        assert s.rate_limit_enabled is False
