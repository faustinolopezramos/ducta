"""Regression: SecurityValidator._is_permissive only checked the mixed-case
`Ducta_PERMISSIVE_PATH_VALIDATION` env var name, not the conventional
all-caps `DUCTA_PERMISSIVE_PATH_VALIDATION` — a very plausible typo/
convention mismatch that would otherwise silently leave permissive mode off.
"""

from __future__ import annotations

from ducta.console.core import SecurityValidator


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
