import os
from unittest.mock import patch

import pytest

from ducta.setting.environments import (
    DEFAULT_ENVIRONMENTS,
    ENV_ALIASES,
    FALLBACK_CHAINS,
    CanonicalEnvironment,
    allowed_environments,
    get_base_environment,
    get_fallback_chain,
    get_sandbox_developer,
    is_allowed_environment,
    is_sandbox_environment,
    is_valid_environment,
    normalize_environment,
)


class TestConstants:
    def test_default_environments(self):
        assert "base" in DEFAULT_ENVIRONMENTS
        assert "dev" in DEFAULT_ENVIRONMENTS
        assert "sandbox" in DEFAULT_ENVIRONMENTS
        assert "staging" in DEFAULT_ENVIRONMENTS
        assert "prod" in DEFAULT_ENVIRONMENTS

    def test_env_aliases(self):
        assert ENV_ALIASES["development"] == "dev"
        assert ENV_ALIASES["production"] == "prod"
        assert ENV_ALIASES["test"] == "sandbox"
        assert ENV_ALIASES["testing"] == "sandbox"


class TestCanonicalEnvironment:
    def test_values(self):
        assert CanonicalEnvironment.BASE.value == "base"
        assert CanonicalEnvironment.DEV.value == "dev"
        assert CanonicalEnvironment.SANDBOX.value == "sandbox"
        assert CanonicalEnvironment.STAGING.value == "staging"
        assert CanonicalEnvironment.PROD.value == "prod"

    def test_str(self):
        assert str(CanonicalEnvironment.DEV) == "dev"

    def test_is_local(self):
        assert CanonicalEnvironment.is_local("base") is True
        assert CanonicalEnvironment.is_local("dev") is True
        assert CanonicalEnvironment.is_local("sandbox") is True
        assert CanonicalEnvironment.is_local("prod") is False
        assert CanonicalEnvironment.is_local("staging") is False

    def test_is_remote(self):
        assert CanonicalEnvironment.is_remote("prod") is True
        assert CanonicalEnvironment.is_remote("staging") is True
        assert CanonicalEnvironment.is_remote("dev") is False

    def test_is_safe(self):
        assert CanonicalEnvironment.is_safe("dev") is True
        assert CanonicalEnvironment.is_safe("sandbox") is True
        assert CanonicalEnvironment.is_safe("prod") is False

    def test_is_testing(self):
        assert CanonicalEnvironment.is_testing("sandbox") is True
        assert CanonicalEnvironment.is_testing("dev") is False


class TestFallbackChains:
    def test_base_chain(self):
        assert FALLBACK_CHAINS["base"] == ["base"]

    def test_dev_chain(self):
        assert FALLBACK_CHAINS["dev"] == ["dev", "base"]

    def test_sandbox_chain(self):
        assert FALLBACK_CHAINS["sandbox"] == ["sandbox", "base"]

    def test_staging_chain(self):
        assert FALLBACK_CHAINS["staging"] == ["staging", "prod", "base"]

    def test_prod_chain(self):
        assert FALLBACK_CHAINS["prod"] == ["prod", "base"]

    def test_get_fallback_chain_sandbox_dev(self):
        assert get_fallback_chain("sandbox_juan") == ["sandbox_juan", "sandbox", "base"]

    def test_get_fallback_chain_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown environment"):
            get_fallback_chain("nonexistent")


class TestIsSandboxEnvironment:
    def test_sandbox(self):
        assert is_sandbox_environment("sandbox") is True

    def test_sandbox_with_developer(self):
        assert is_sandbox_environment("sandbox_juan") is True

    def test_not_sandbox(self):
        assert is_sandbox_environment("dev") is False
        assert is_sandbox_environment("") is False


class TestGetSandboxDeveloper:
    def test_generic_sandbox(self):
        assert get_sandbox_developer("sandbox") is None

    def test_sandbox_with_developer(self):
        assert get_sandbox_developer("sandbox_juan") == "juan"

    def test_not_sandbox(self):
        assert get_sandbox_developer("prod") is None


class TestGetBaseEnvironment:
    def test_sandbox_dev_returns_sandbox(self):
        assert get_base_environment("sandbox_juan") == "sandbox"

    def test_sandbox_returns_sandbox(self):
        assert get_base_environment("sandbox") == "sandbox"

    def test_dev_returns_dev(self):
        assert get_base_environment("dev") == "dev"


class TestIsValidEnvironment:
    def test_valid_environments(self):
        assert is_valid_environment("base") is True
        assert is_valid_environment("dev") is True
        assert is_valid_environment("sandbox") is True
        assert is_valid_environment("staging") is True
        assert is_valid_environment("prod") is True

    def test_valid_aliases(self):
        assert is_valid_environment("development") is True
        assert is_valid_environment("production") is True
        assert is_valid_environment("test") is True

    def test_sandbox_with_dev(self):
        assert is_valid_environment("sandbox_juan") is True

    def test_invalid(self):
        assert is_valid_environment("invalid") is False
        assert is_valid_environment("") is False
        assert is_valid_environment(None) is False


class TestNormalizeEnvironment:
    def test_none_or_empty(self):
        assert normalize_environment(None) is None
        assert normalize_environment("") is None

    def test_aliases(self):
        assert normalize_environment("development") == "dev"
        assert normalize_environment("production") == "prod"
        assert normalize_environment("test") == "sandbox"
        assert normalize_environment("testing") == "sandbox"

    def test_sandbox_passthrough(self):
        assert normalize_environment("sandbox") == "sandbox"

    def test_sandbox_with_dev(self):
        assert normalize_environment("sandbox_juan") == "sandbox_juan"

    def test_sandbox_dev_sanitized(self):
        assert normalize_environment("sandbox_juan!") == "sandbox_juan"

    def test_already_normalized(self):
        assert normalize_environment("dev") == "dev"
        assert normalize_environment("prod") == "prod"


class TestAllowedEnvironments:
    def test_allowed_returns_defaults(self):
        envs = allowed_environments()
        assert "base" in envs
        assert "dev" in envs
        assert "prod" in envs

    def test_allowed_with_env_var(self):
        with patch.dict(os.environ, {"DUCTA_ALLOWED_ENVS": "custom1,custom2"}, clear=True):
            envs = allowed_environments()
            assert "custom1" in envs
            assert "custom2" in envs


class TestIsAllowedEnvironment:
    def test_allowed_environment(self):
        assert is_allowed_environment("dev") is True

    def test_sandbox_always_allowed(self):
        assert is_allowed_environment("sandbox") is True
        assert is_allowed_environment("sandbox_juan") is True

    def test_invalid_not_allowed(self):
        assert is_allowed_environment("nonexistent") is False

    def test_invalid_type(self):
        assert is_allowed_environment(None) is False
