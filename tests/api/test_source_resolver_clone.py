"""Regression tests for `SourceResolver._clone_or_update`'s redirect hardening.

`Repo.clone_from`/`origin.pull()` used no options at all, so a malicious or
compromised remote could 301/302-redirect the clone/fetch to a different host
than the one `_enforce_clone_host_allowlist` validated (git follows HTTP
redirects by default). `-c http.followRedirects=false` (injected via
GIT_CONFIG_* env, since `-c` itself is in GitPython's unsafe-clone-options
list) closes that; `--no-tags` avoids following extra tag refs.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ducta.api.source.resolver import SourceResolver


@pytest.fixture(autouse=True)
def _allowlist_github(monkeypatch):
    """Skip the DNS-resolution SSRF check by explicitly allow-listing the
    test host, so these tests don't need real network access."""
    settings = SimpleNamespace(git_clone_allowed_hosts=["github.com"])
    monkeypatch.setattr("ducta.api.config.get_settings", lambda: settings)


class TestCloneAppliesRedirectGuard:
    def test_clone_from_disables_redirects_and_tags(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            SourceResolver, "_clone_path", classmethod(lambda cls, url: tmp_path / "repo")
        )
        mock_repo_cls = MagicMock()
        with patch("git.Repo", mock_repo_cls):
            SourceResolver._clone_or_update("https://github.com/user/repo.git")

        assert mock_repo_cls.clone_from.call_count == 1
        _, kwargs = mock_repo_cls.clone_from.call_args
        assert kwargs["env"] == {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.followRedirects",
            "GIT_CONFIG_VALUE_0": "false",
        }
        assert kwargs["no_tags"] is True

    def test_pull_disables_redirects_and_tags(self, tmp_path, monkeypatch):
        clone_dir = tmp_path / "repo"
        (clone_dir / ".git").mkdir(parents=True)
        monkeypatch.setattr(SourceResolver, "_clone_path", classmethod(lambda cls, url: clone_dir))

        mock_origin = MagicMock()
        mock_repo_instance = MagicMock()
        mock_repo_instance.remotes = MagicMock()
        mock_repo_instance.remotes.origin = mock_origin
        mock_repo_instance.git.custom_environment.return_value.__enter__ = MagicMock()
        mock_repo_instance.git.custom_environment.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_repo_cls = MagicMock()
        mock_repo_cls.return_value = mock_repo_instance
        with patch("git.Repo", mock_repo_cls):
            SourceResolver._clone_or_update("https://github.com/user/repo.git")

        mock_repo_instance.git.custom_environment.assert_called_once_with(
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="http.followRedirects",
            GIT_CONFIG_VALUE_0="false",
        )
        mock_origin.pull.assert_called_once_with(no_tags=True)
