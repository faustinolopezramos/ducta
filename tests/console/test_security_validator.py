"""Regression: SecurityValidator._is_permissive only checked the mixed-case
`Ducta_PERMISSIVE_PATH_VALIDATION` env var name, not the conventional
all-caps `DUCTA_PERMISSIVE_PATH_VALIDATION` — a very plausible typo/
convention mismatch that would otherwise silently leave permissive mode off.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ducta.console.core import SecurityError, SecurityValidator


class TestIsPermissive:
    def test_defaults_to_false(self, monkeypatch):
        monkeypatch.delenv("Ducta_PERMISSIVE_PATH_VALIDATION", raising=False)
        monkeypatch.delenv("DUCTA_PERMISSIVE_PATH_VALIDATION", raising=False)
        assert SecurityValidator._is_permissive() is False

    def test_historical_mixed_case_name_still_works(self, monkeypatch):
        monkeypatch.setenv("Ducta_PERMISSIVE_PATH_VALIDATION", "1")
        monkeypatch.delenv("DUCTA_PERMISSIVE_PATH_VALIDATION", raising=False)
        assert SecurityValidator._is_permissive() is True

    def test_conventional_all_caps_name_works(self, monkeypatch):
        monkeypatch.delenv("Ducta_PERMISSIVE_PATH_VALIDATION", raising=False)
        monkeypatch.setenv("DUCTA_PERMISSIVE_PATH_VALIDATION", "true")
        assert SecurityValidator._is_permissive() is True


class TestValidatePathWithinBase:
    def test_path_inside_base_is_accepted(self, tmp_path):
        target = tmp_path / "sub" / "file.yaml"
        target.parent.mkdir(parents=True)
        target.write_text("x")

        result = SecurityValidator.validate_path(tmp_path, target)

        assert result == target.resolve()

    def test_path_outside_base_is_rejected(self, tmp_path):
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "outside_file.yaml"

        with pytest.raises(SecurityError, match="traversal"):
            SecurityValidator.validate_path(base, outside)


class TestCheckSensitiveDirs:
    def test_path_under_a_sensitive_dir_is_rejected(self):
        if os.name != "posix":
            pytest.skip("POSIX-specific sensitive dirs")
        with pytest.raises(SecurityError, match="sensitive directory"):
            SecurityValidator._check_sensitive_dirs(Path("/etc/passwd"))

    def test_ordinary_path_is_accepted(self, tmp_path):
        SecurityValidator._check_sensitive_dirs(tmp_path / "project" / "file.yaml")


class TestCheckHiddenParts:
    """Regression: _check_hidden_parts used to iterate resolved_target's
    full absolute path, so a base_path with a dotdir ancestor (e.g.
    ~/.config/ducta_projects/proj) rejected every path underneath it, even
    with nothing hidden relative to base_path itself."""

    def test_hidden_component_relative_to_base_is_rejected(self, tmp_path):
        base = tmp_path / "project"
        target = base / ".secret" / "file.yaml"

        with pytest.raises(SecurityError, match="hidden path"):
            SecurityValidator._check_hidden_parts(base, target)

    def test_no_hidden_component_relative_to_base_is_accepted(self, tmp_path):
        base = tmp_path / "project"
        target = base / "config" / "file.yaml"

        SecurityValidator._check_hidden_parts(base, target)  # must not raise

    def test_base_path_itself_under_a_dotdir_ancestor_is_not_flagged(self, tmp_path):
        base = tmp_path / ".hidden_root" / "project"
        target = base / "config" / "file.yaml"

        SecurityValidator._check_hidden_parts(base, target)  # must not raise

    def test_validate_path_end_to_end_with_base_under_a_dotdir_ancestor(self, tmp_path):
        base = tmp_path / ".hidden_root" / "project"
        base.mkdir(parents=True)
        target = base / "config.yaml"
        target.write_text("x")

        result = SecurityValidator.validate_path(base, target)

        assert result == target.resolve()
