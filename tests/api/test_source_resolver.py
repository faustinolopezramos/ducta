"""Unit tests for ducta.api.source.resolver.SourceResolver (SSRF + parsing)."""

from __future__ import annotations

import pathlib

import pytest

from ducta.api.source.resolver import SourceResolver as SR


class TestExtractGitHost:
    def test_https(self):
        assert SR._extract_git_host("https://github.com/user/repo.git") == "github.com"

    def test_scp_style(self):
        assert SR._extract_git_host("git@gitlab.com:group/proj.git") == "gitlab.com"

    def test_non_url(self):
        assert SR._extract_git_host("/local/path") is None


class TestExtractRepoName:
    def test_https(self):
        assert SR._extract_repo_name("https://github.com/user/repo.git") == "repo"

    def test_scp(self):
        assert SR._extract_repo_name("git@host:group/proj.git") == "proj"

    def test_sanitized(self):
        # non-alnum chars collapse to underscore
        assert SR._extract_repo_name("https://h/a b!.git") == "a_b_"


class TestNormalizeSourceInput:
    def test_strips_double_quotes(self):
        assert SR._normalize_source_input('"  /path/x  "') == "/path/x"

    def test_strips_single_quotes(self):
        assert SR._normalize_source_input("'/path/y'") == "/path/y"

    def test_plain(self):
        assert SR._normalize_source_input("  /plain  ") == "/plain"


class TestIsGitUrl:
    def test_https_git(self):
        assert SR.is_git_url("https://github.com/u/r.git") is True

    def test_local_path(self):
        assert SR.is_git_url("/home/user/project") is False


class TestSSRFRejectInternalHost:
    @pytest.mark.parametrize(
        "host",
        ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1"],
    )
    def test_internal_hosts_rejected(self, host):
        with pytest.raises(ValueError, match="internal/non-routable"):
            SR._reject_internal_host(host)

    def test_public_ip_allowed(self):
        # IP literal avoids any DNS lookup; must not raise
        SR._reject_internal_host("8.8.8.8")

    def test_empty_host_rejected(self):
        with pytest.raises(ValueError):
            SR._reject_internal_host(None)


class TestResolveLocalConfinement:
    """Regression: `resolve_local` used to skip relative-to-base confinement
    entirely for absolute paths, relying only on a denylist of a handful of
    sensitive directories (/etc, /proc, /root, ...) — any other directory the
    server process could read was accepted as a workspace, and that workspace
    is later inserted into `sys.path` and imported from (execution/runner.py).
    Confinement always runs; the base is the enclosing workspace, falling back
    to the cwd when the server was not started inside one."""

    def test_directory_outside_the_base_is_rejected(self, tmp_path, monkeypatch):
        outside = tmp_path / "outside"
        outside.mkdir()
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        with pytest.raises(ValueError, match="outside the workspace"):
            SR.resolve_local(str(outside))

    def test_the_rejection_says_how_to_fix_it(self, tmp_path, monkeypatch):
        # The old wording was "Path traversal attempt blocked", which reads as
        # an accusation for what is nearly always a workspace/server mismatch.
        outside = tmp_path / "outside"
        outside.mkdir()
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        with pytest.raises(ValueError) as excinfo:
            SR.resolve_local(str(outside))
        message = str(excinfo.value)
        assert "traversal" not in message.lower()
        assert str(cwd.resolve()) in message, "must name the directory the server can reach"
        assert "--source" in message, "must name a way out"

    def test_directory_inside_cwd_is_allowed(self, tmp_path, monkeypatch):
        cwd = tmp_path / "cwd"
        (cwd / "project").mkdir(parents=True)
        monkeypatch.chdir(cwd)

        resolved = SR.resolve_local(str(cwd / "project"))
        assert resolved == (cwd / "project").resolve()

    def test_sensitive_dir_still_rejected_even_if_somehow_under_cwd(self, tmp_path, monkeypatch):
        # Belt-and-suspenders: the sensitive-dirs denylist must still apply
        # on top of (not instead of) the cwd confinement.
        fake_ssh = tmp_path / ".ssh"
        fake_ssh.mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "ducta.console.core.SecurityValidator.SENSITIVE_DIRS",
            (fake_ssh,),
        )

        with pytest.raises(ValueError, match="Path validation failed"):
            SR.resolve_local(str(fake_ssh))


class TestWorkspaceRootIsReachableFromAProjectDirectory:
    """`ducta ui` is normally launched from inside a project, and the workspace
    root sits *above* that. Confining to the raw cwd rejected the workspace as a
    traversal attempt and took every source-dependent endpoint down with it —
    all while `normalize_workspace_path` and `_detect_ducta_workspace` were
    walking upward to find that very directory.
    """

    @staticmethod
    def _workspace(tmp_path):
        """A multi-project workspace: env files live in projects/<name>/."""
        root = tmp_path / "demo"
        project = root / "projects" / "streaming"
        project.mkdir(parents=True)
        (project / "environment.toml").write_text("[env_config]\n", encoding="utf-8")
        return root, project

    def test_the_workspace_root_resolves_from_inside_a_project(self, tmp_path, monkeypatch):
        root, project = self._workspace(tmp_path)
        monkeypatch.chdir(project)

        assert SR.resolve_local(str(root)) == root.resolve()

    def test_sibling_projects_resolve_too(self, tmp_path, monkeypatch):
        root, project = self._workspace(tmp_path)
        sibling = root / "projects" / "batch"
        sibling.mkdir()
        monkeypatch.chdir(project)

        assert SR.resolve_local(str(sibling)) == sibling.resolve()

    def test_nothing_above_the_workspace_becomes_reachable(self, tmp_path, monkeypatch):
        # Widening the base to the workspace must not widen it to its parent.
        root, project = self._workspace(tmp_path)
        outsider = tmp_path / "unrelated"
        outsider.mkdir()
        monkeypatch.chdir(project)

        with pytest.raises(ValueError, match="outside the workspace"):
            SR.resolve_local(str(outsider))

    def test_without_a_workspace_the_cwd_remains_the_base(self, tmp_path, monkeypatch):
        plain = tmp_path / "plain"
        (plain / "inner").mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        monkeypatch.chdir(plain)

        assert SR.resolve_local(str(plain / "inner")) == (plain / "inner").resolve()
        with pytest.raises(ValueError):
            SR.resolve_local(str(outside))

    def test_home_is_never_adopted_as_the_workspace(self, tmp_path, monkeypatch):
        # A stray ~/config or ~/projects must not make the whole home directory
        # addressable. The walk stops before $HOME.
        home = tmp_path / "home"
        (home / "projects").mkdir(parents=True)
        start = home / "projects" / "thing"
        start.mkdir()
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
        monkeypatch.chdir(start)

        assert SR._confinement_base() != home

    def test_an_explicit_ducta_workspace_is_honoured(self, tmp_path, monkeypatch):
        # `ducta ui --source` exports DUCTA_WORKSPACE; the base follows it
        # rather than whatever directory the process happens to sit in.
        root, project = self._workspace(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        monkeypatch.setenv("DUCTA_WORKSPACE", str(project))

        assert SR.resolve_local(str(root)) == root.resolve()
