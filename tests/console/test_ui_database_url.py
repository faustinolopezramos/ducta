"""Regression: `launch_ui` used `not os.environ.get("DATABASE_URL")` to
decide whether to set a default SQLite path — `not ""` is True, so an
explicit `DATABASE_URL=""` opt-out (documented in the code's own comment)
was treated identically to "unset" and silently overwritten with the
default path anyway.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from ducta.console.ui import launch_ui


class TestLaunchUiRespectsExplicitDatabaseUrlOptOut:
    def test_empty_string_opt_out_is_respected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", "")
        with patch("uvicorn.run", MagicMock()):
            launch_ui(
                open_browser=False,
                db_path=str(tmp_path / "db.sqlite"),
            )
        assert os.environ["DATABASE_URL"] == ""

    def test_unset_gets_the_default_sqlite_path(self, monkeypatch, tmp_path):
        # setenv first so teardown restores the original state: delenv of an
        # absent variable records nothing, and launch_ui then sets it for good,
        # leaking a table-less database into every later test that builds the app.
        monkeypatch.setenv("DATABASE_URL", "placeholder")
        monkeypatch.delenv("DATABASE_URL")
        db_path = tmp_path / "db.sqlite"
        with patch("uvicorn.run", MagicMock()):
            launch_ui(open_browser=False, db_path=str(db_path))
        assert os.environ["DATABASE_URL"] == f"sqlite+aiosqlite:///{db_path}"

    def test_explicit_non_empty_value_is_respected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")
        with patch("uvicorn.run", MagicMock()):
            launch_ui(open_browser=False, db_path=str(tmp_path / "db.sqlite"))
        assert os.environ["DATABASE_URL"] == "postgresql+asyncpg://x/y"
