"""Regression: certify_cmds._resolve_run built `runs_dir / run_id /
"certificate.json"` straight from --run-id without validating its charset —
unlike template.py's --project-name/--sandbox-developers, which already
guard the same path-component-from-CLI-input pattern with VALID_NAME_RE.
A run_id like "../../../../etc" could resolve outside runs_dir.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ducta.console.commands import certify_cmds
from ducta.console.commands.certify_cmds import _candidate_runs_dirs, _resolve_run
from ducta.setting.environments import DEFAULT_ENVIRONMENTS


def _args(runs_dir, run_id):
    return SimpleNamespace(dir=str(runs_dir), run_id=run_id)


class TestResolveRunValidatesRunId:
    def test_valid_run_id_resolves_the_certificate(self, tmp_path):
        run_dir = tmp_path / "abc12345"
        run_dir.mkdir()
        (run_dir / "certificate.json").write_text("{}")

        result = _resolve_run(_args(tmp_path, "abc12345"))

        assert result == run_dir / "certificate.json"

    def test_path_traversal_run_id_is_rejected(self, tmp_path):
        # A file that a successful traversal would have reached.
        (tmp_path / "escaped_certificate.json").write_text("{}")

        result = _resolve_run(_args(tmp_path / "runs", "../escaped"))

        assert result is None

    def test_run_id_with_path_separator_is_rejected(self, tmp_path):
        result = _resolve_run(_args(tmp_path, "sub/dir"))

        assert result is None

    def test_missing_run_id_is_still_reported_as_required(self, tmp_path):
        result = _resolve_run(_args(tmp_path, None))

        assert result is None


class TestCandidateRunsDirs:
    """Under the Ducta storage convention, each environment gets its own
    run_certificate_dir (no single tree holds every environment anymore), so
    `certify list/show/verify/diff` must discover candidate directories
    instead of assuming one. See CoreSettings._resolve_scoped_dir.
    """

    def test_explicit_dir_is_a_hard_override_and_skips_discovery(self, tmp_path, monkeypatch):
        def _fail(*a, **k):
            raise AssertionError("should not resolve via project config when --dir is given")

        monkeypatch.setattr(certify_cmds, "_resolve_run_certificate_dir", _fail)
        args = SimpleNamespace(dir=str(tmp_path / "custom"), env=None, base_path=None)

        assert _candidate_runs_dirs(args) == [(None, tmp_path / "custom")]

    def test_env_arg_resolves_a_single_candidate(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # isolate from any real .ducta/runs at the real cwd
        resolved = tmp_path / "data" / "dev" / ".ducta" / "runs"
        resolved.mkdir(parents=True)

        monkeypatch.setattr(
            certify_cmds,
            "_resolve_run_certificate_dir",
            lambda parsed_args, env: resolved if env == "dev" else None,
        )
        args = SimpleNamespace(dir=None, env="dev", base_path=None)

        assert _candidate_runs_dirs(args) == [("dev", resolved)]

    def test_no_dir_or_env_discovers_every_existing_canonical_environment(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)  # isolate from any real .ducta/runs at the real cwd
        existing = {"dev", "prod"}

        def _fake_resolve(parsed_args, env):
            d = tmp_path / "data" / env / ".ducta" / "runs"
            if env in existing:
                d.mkdir(parents=True)
            return d

        monkeypatch.setattr(certify_cmds, "_resolve_run_certificate_dir", _fake_resolve)
        args = SimpleNamespace(dir=None, env=None, base_path=None)

        candidates = _candidate_runs_dirs(args)

        assert {env for env, _ in candidates} == existing
        assert set(DEFAULT_ENVIRONMENTS) >= existing  # sanity: fixture stays in range

    def test_an_environment_that_cannot_be_resolved_is_skipped_not_raised(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)  # isolate from any real .ducta/runs at the real cwd

        def _fake_resolve(parsed_args, env):
            if env == "dev":
                d = tmp_path / "data" / "dev" / ".ducta" / "runs"
                d.mkdir(parents=True)
                return d
            return None  # e.g. no config file for this environment

        monkeypatch.setattr(certify_cmds, "_resolve_run_certificate_dir", _fake_resolve)
        args = SimpleNamespace(dir=None, env=None, base_path=None)

        candidates = _candidate_runs_dirs(args)

        assert [env for env, _ in candidates] == ["dev"]

    def test_a_pre_convention_legacy_runs_dir_stays_discoverable(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        legacy = tmp_path / ".ducta" / "runs"
        legacy.mkdir(parents=True)
        monkeypatch.setattr(
            certify_cmds, "_resolve_run_certificate_dir", lambda parsed_args, env: None
        )
        args = SimpleNamespace(dir=None, env=None, base_path=None)

        candidates = _candidate_runs_dirs(args)

        assert candidates == [(None, Path(".ducta/runs"))]

    def test_no_legacy_dir_means_no_extra_candidate(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            certify_cmds, "_resolve_run_certificate_dir", lambda parsed_args, env: None
        )
        args = SimpleNamespace(dir=None, env=None, base_path=None)

        assert _candidate_runs_dirs(args) == []
