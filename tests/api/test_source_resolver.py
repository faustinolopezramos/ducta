"""Unit tests for ducta.api.source.resolver.SourceResolver (SSRF + parsing)."""

from __future__ import annotations

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


class TestResolveLocalConfinesToCwd:
    """Regression: `resolve_local` used to skip relative-to-base confinement
    entirely for absolute paths, relying only on a denylist of a handful of
    sensitive directories (/etc, /proc, /root, ...) — any other directory the
    server process could read was accepted as a workspace, and that workspace
    is later inserted into `sys.path` and imported from (execution/runner.py).
    Confinement now always runs, using the server's cwd as the base."""

    def test_directory_outside_cwd_is_rejected(self, tmp_path, monkeypatch):
        outside = tmp_path / "outside"
        outside.mkdir()
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        with pytest.raises(ValueError, match="Path validation failed"):
            SR.resolve_local(str(outside))

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
