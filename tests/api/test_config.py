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


class TestGitCloneHostDefault:
    """An unset clone allow-list must not mean "any host" on a networked deploy.

    The clone target comes from a caller-supplied `?source=`, so an empty list
    let a deployment be pointed at any internal URL and clone it with the
    server's own network position (SSRF). The field's description warned about
    exactly this while the default shipped the permissive value.
    """

    def test_development_still_allows_any_host(self):
        # Cloning from a LAN mirror or a local bare repo is normal in dev, and
        # the API binds to loopback there.
        s = Settings(environment="development")
        assert s.git_clone_allowed_hosts == []

    @pytest.mark.parametrize("environment", ["staging", "production"])
    def test_other_environments_get_the_public_forges(self, environment):
        s = Settings(
            environment=environment,
            auth_enabled=True,
            jwt_secret_key="not-the-default",
        )
        assert "github.com" in s.git_clone_allowed_hosts
        assert "dev.azure.com" in s.git_clone_allowed_hosts
        assert s.git_clone_allowed_hosts != []

    def test_an_explicit_list_is_never_overridden(self):
        s = Settings(
            environment="production",
            auth_enabled=True,
            jwt_secret_key="not-the-default",
            git_clone_allowed_hosts=["git.internal"],
        )
        assert s.git_clone_allowed_hosts == ["git.internal"]

    def test_the_default_list_is_not_shared_between_instances(self):
        # A mutable class attribute handed out by reference would let one
        # Settings object's edit leak into the next.
        first = Settings(environment="staging")
        first.git_clone_allowed_hosts.append("leaked.example")
        second = Settings(environment="staging")
        assert "leaked.example" not in second.git_clone_allowed_hosts
