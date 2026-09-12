"""Regression tests for the shared push/pull/redaction template in `RepositoryAdapter`.

`GitHubAdapter`, `AzureAdapter`, and `AWSAdapter` used to each hand-roll their own
`push()`/`pull()`/`_require_local_path()` (byte-identical logic) and error redaction.
That logic now lives once in `RepositoryAdapter` (vcs/base.py), with subclasses only
supplying `_provider_name` and `_secret_values()`. These tests guard: (1) the shared
"no local path" guard still raises the same error shape for every adapter, and (2)
`_secret_values()` closes the redaction gap AWS previously had — a raw credential
value leaking into an exception message (not just one embedded in a URL) is scrubbed.

Instances are built with `object.__new__` + manual attribute assignment rather than
the real constructors, since the constructors import optional third-party SDKs
(PyGithub, azure-devops, boto3) that aren't installed in this dev environment and
aren't needed to exercise the shared adapter logic under test here.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ducta.api.exceptions import RepositoryAdapterError
from ducta.api.vcs.aws import AWSAdapter
from ducta.api.vcs.azure import AzureAdapter
from ducta.api.vcs.github import GitHubAdapter


def _make_github(local_path=None) -> GitHubAdapter:
    adapter = object.__new__(GitHubAdapter)
    adapter._token = "ghp_secrettoken"
    adapter._org = "acme"
    adapter._repo_name = "widgets"
    adapter._local_path = local_path
    return adapter


def _make_azure(local_path=None) -> AzureAdapter:
    adapter = object.__new__(AzureAdapter)
    adapter._token = "azpat_secrettoken"
    adapter._org = "https://dev.azure.com/acme"
    adapter._project = "widgets"
    adapter._repo_name = "widgets"
    adapter._local_path = local_path
    return adapter


def _make_aws(local_path=None, https_creds=True) -> AWSAdapter:
    adapter = object.__new__(AWSAdapter)
    adapter._region = "us-east-1"
    adapter._repo_name = "widgets"
    adapter._access_key = "AKIASECRETID"
    adapter._secret_key = "supersecretkey"
    adapter._https_username = "svc-user" if https_creds else None
    adapter._https_password = "supersecretkey" if https_creds else None
    adapter._local_path = local_path
    return adapter


ADAPTER_FACTORIES = {
    "github": _make_github,
    "azure": _make_azure,
    "aws": _make_aws,
}


def _mock_repo_raising(method_name: str, message: str) -> MagicMock:
    """A fake GitPython Repo whose git.<method_name>() raises RuntimeError(message)."""
    fake_repo = MagicMock()
    fake_repo.git.custom_environment.return_value.__enter__ = MagicMock()
    fake_repo.git.custom_environment.return_value.__exit__ = MagicMock(return_value=False)
    getattr(fake_repo.git, method_name).side_effect = RuntimeError(message)
    return fake_repo


class TestRequireLocalPath:
    @pytest.mark.parametrize("name", ADAPTER_FACTORIES)
    def test_push_without_local_path_raises(self, name):
        adapter = ADAPTER_FACTORIES[name](local_path=None)
        with pytest.raises(RepositoryAdapterError, match="local path"):
            adapter.push()

    @pytest.mark.parametrize("name", ADAPTER_FACTORIES)
    def test_pull_without_local_path_raises(self, name):
        adapter = ADAPTER_FACTORIES[name](local_path=None)
        with pytest.raises(RepositoryAdapterError, match="local path"):
            adapter.pull()


class TestProviderNameInErrorMessage:
    @pytest.mark.parametrize(
        "name,expected_prefix",
        [
            ("github", "GitHub push failed"),
            ("azure", "Azure push failed"),
            ("aws", "AWS push failed"),
        ],
    )
    def test_push_error_is_prefixed_with_provider_name(self, name, expected_prefix):
        adapter = ADAPTER_FACTORIES[name](local_path="/tmp/fake-repo")
        fake_repo = _mock_repo_raising("push", "boom")
        with (
            patch("ducta.api.vcs.base.get_repo", return_value=fake_repo),
            patch("ducta.api.vcs.base.GIT_AVAILABLE", True),
        ):
            with pytest.raises(RepositoryAdapterError) as exc_info:
                adapter.push()
        assert str(exc_info.value).startswith(expected_prefix)


class TestSecretRedaction:
    def test_github_scrubs_raw_token_from_push_error(self):
        adapter = _make_github(local_path="/tmp/fake-repo")
        fake_repo = _mock_repo_raising("push", "auth failed for token ghp_secrettoken")
        with (
            patch("ducta.api.vcs.base.get_repo", return_value=fake_repo),
            patch("ducta.api.vcs.base.GIT_AVAILABLE", True),
        ):
            with pytest.raises(RepositoryAdapterError) as exc_info:
                adapter.push()
        assert "ghp_secrettoken" not in str(exc_info.value)
        assert "***" in str(exc_info.value)

    def test_azure_scrubs_raw_token_from_pull_error(self):
        adapter = _make_azure(local_path="/tmp/fake-repo")
        fake_repo = _mock_repo_raising("pull", "bad credentials azpat_secrettoken")
        with (
            patch("ducta.api.vcs.base.get_repo", return_value=fake_repo),
            patch("ducta.api.vcs.base.GIT_AVAILABLE", True),
        ):
            with pytest.raises(RepositoryAdapterError) as exc_info:
                adapter.pull()
        assert "azpat_secrettoken" not in str(exc_info.value)
        assert "***" in str(exc_info.value)

    def test_aws_scrubs_raw_secret_key_from_push_error(self):
        """Regression test for the gap this refactor closes: AWS previously only
        redacted credentials embedded in URLs (via `redact_git_credentials`), not a
        raw secret key appearing elsewhere in an error message (e.g. boto3/git
        stderr). `_secret_values()` now gives AWS the same second-pass scrub
        GitHub/Azure already had for their token."""
        adapter = _make_aws(local_path="/tmp/fake-repo")
        fake_repo = _mock_repo_raising("push", "connection refused using secret supersecretkey")
        with (
            patch("ducta.api.vcs.base.get_repo", return_value=fake_repo),
            patch("ducta.api.vcs.base.GIT_AVAILABLE", True),
        ):
            with pytest.raises(RepositoryAdapterError) as exc_info:
                adapter.push()
        assert "supersecretkey" not in str(exc_info.value)
        assert "AKIASECRETID" not in str(exc_info.value)
        assert "***" in str(exc_info.value)

    def test_aws_secret_values_filters_falsy_entries(self):
        """AWS adapters without HTTPS creds configured should not blow up
        _safe_error with None entries in _secret_values()."""
        adapter = _make_aws(https_creds=False)
        adapter._access_key = None
        adapter._secret_key = None
        assert adapter._secret_values() == []
        assert adapter._safe_error(RuntimeError("plain error")) == "plain error"

    def test_aws_secret_values_includes_all_configured_credentials(self):
        adapter = _make_aws()
        values = adapter._secret_values()
        assert "AKIASECRETID" in values
        assert "supersecretkey" in values
