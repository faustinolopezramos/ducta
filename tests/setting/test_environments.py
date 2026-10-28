import os
from unittest.mock import patch

import pytest

from ducta.setting.environments import (
    DEFAULT_ENVIRONMENTS,
    ENV_ALIASES,
    get_base_environment,
    is_sandbox_environment,
    normalize_environment,
    sanitize_env_for_path,
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


class TestIsSandboxEnvironment:
    def test_sandbox(self):
        assert is_sandbox_environment("sandbox") is True

    def test_sandbox_with_developer(self):
        assert is_sandbox_environment("sandbox_juan") is True

    def test_not_sandbox(self):
        assert is_sandbox_environment("dev") is False
        assert is_sandbox_environment("") is False


class TestGetBaseEnvironment:
    def test_sandbox_dev_returns_sandbox(self):
        assert get_base_environment("sandbox_juan") == "sandbox"

    def test_sandbox_returns_sandbox(self):
        assert get_base_environment("sandbox") == "sandbox"

    def test_dev_returns_dev(self):
        assert get_base_environment("dev") == "dev"


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


class TestSanitizeEnvForPath:
    """Used to build .ducta/chain_state/<env>/... and .ducta/runs/<env>/... segments."""

    def test_none_falls_back_to_base(self):
        assert sanitize_env_for_path(None) == "base"

    def test_empty_string_falls_back_to_base(self):
        assert sanitize_env_for_path("") == "base"

    def test_plain_env_name_is_unchanged(self):
        assert sanitize_env_for_path("dev") == "dev"
        assert sanitize_env_for_path("prod") == "prod"
        assert sanitize_env_for_path("sandbox_juan") == "sandbox_juan"

    def test_path_separators_are_stripped(self):
        assert "/" not in sanitize_env_for_path("dev/../../etc")
        assert "\\" not in sanitize_env_for_path("dev\\..\\etc")

    def test_traversal_sequence_cannot_escape_the_base_dir(self):
        result = sanitize_env_for_path("../../../etc/passwd")
        assert ".." not in result
        assert "/" not in result
