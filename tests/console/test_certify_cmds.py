"""Regression: certify_cmds._resolve_run built `runs_dir / run_id /
"certificate.json"` straight from --run-id without validating its charset —
unlike template.py's --project-name/--sandbox-developers, which already
guard the same path-component-from-CLI-input pattern with VALID_NAME_RE.
A run_id like "../../../../etc" could resolve outside runs_dir.
"""

from __future__ import annotations

from types import SimpleNamespace

from ducta.console.commands.certify_cmds import _resolve_run


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
