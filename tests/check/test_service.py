"""Unit tests for ducta.check.service.QualityService."""

from __future__ import annotations

import pytest

from ducta.check.service import QualityService


class TestGetScore:
    def test_missing_workspace_gives_clear_message(self, tmp_path):
        """Regression: the "no quality data at all" guard must actually fire —
        it previously checked '.quality'.exists() *after* constructing
        FileStorageBackend, whose __init__ creates that very directory as a
        side effect, so the guard was dead code and users only ever saw the
        less specific "No quality reports found for run_id ..." message."""
        empty_workspace = tmp_path / "empty"
        empty_workspace.mkdir()

        with pytest.raises(FileNotFoundError, match="No quality data found"):
            QualityService.get_score("run1", workspace=str(empty_workspace))
