"""`WorkspaceManager.info()` must not hand back credentials.

A git remote can carry them inline — `https://user:token@host/repo.git` — and
`info()` returned `repo.remotes[0].url` verbatim into a value shaped for a
response body. The two other places that surface the same field
(`SourceResolver.get_info` and `routes/workspace.py`) already run it through
`sanitize_git_remote_url`; this one was the odd one out.
"""

from __future__ import annotations

import pytest

from ducta.api.utils.git_utils import GIT_AVAILABLE
from ducta.api.workspace.manager import WorkspaceManager

pytestmark = pytest.mark.skipif(not GIT_AVAILABLE, reason="GitPython not installed")


def _repo_with_remote(path, url: str):
    from git import Repo

    repo = Repo.init(path)
    repo.create_remote("origin", url)
    return repo


class TestInfoRedactsRemoteCredentials:
    def test_password_is_stripped_from_an_https_remote(self, tmp_path):
        _repo_with_remote(tmp_path, "https://user:ghp_sekrit@github.com/acme/repo.git")

        info = WorkspaceManager(tmp_path).info()

        assert "ghp_sekrit" not in info["git_remote"]
        assert "user" not in info["git_remote"]
        assert info["git_remote"] == "https://github.com/acme/repo.git"

    def test_a_token_only_userinfo_is_stripped(self, tmp_path):
        # GitHub PATs are commonly embedded with no password half at all.
        _repo_with_remote(tmp_path, "https://ghp_sekrit@github.com/acme/repo.git")

        assert "ghp_sekrit" not in WorkspaceManager(tmp_path).info()["git_remote"]

    def test_a_clean_remote_is_returned_unchanged(self, tmp_path):
        url = "https://github.com/acme/repo.git"
        _repo_with_remote(tmp_path, url)

        assert WorkspaceManager(tmp_path).info()["git_remote"] == url

    def test_an_ssh_remote_keeps_its_user(self, tmp_path):
        # `git@host:path` is the ordinary SSH form — the "user" there is not a
        # credential and must survive, or every SSH remote renders wrong.
        url = "git@github.com:acme/repo.git"
        _repo_with_remote(tmp_path, url)

        assert WorkspaceManager(tmp_path).info()["git_remote"] == url

    def test_a_workspace_without_git_reports_no_remote(self, tmp_path):
        info = WorkspaceManager(tmp_path).info()

        assert info["has_git"] is False
        assert info["git_remote"] is None
