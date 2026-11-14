"""``ducta-server user``: the accounts that may sign in.

Only ``admin`` could exist (seeded from the environment), so the developer, operator and
viewer roles, and the protection of production environments, could not be reached.
"""

from __future__ import annotations

import asyncio

import pytest

from ducta_server.auth.service import get_auth_service
from ducta_server.config import get_settings
from ducta_server.db import engine as db_engine
from ducta_server.db import session as db_session
from ducta_server.db.migrate import run_migrations
from ducta_server.db.stores.user_store import DatabaseUserStore, UserAdminError

PASSWORD = "a-long-enough-password"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'users.db'}")
    get_settings.cache_clear()
    for module, name in ((db_engine, "_engine"), (db_session, "_session_factory")):
        monkeypatch.setattr(module, name, None, raising=False)
    monkeypatch.setattr("ducta_server.db.migrate._migrations_run", False, raising=False)
    engine = db_engine.get_engine()
    asyncio.run(run_migrations(engine))
    yield DatabaseUserStore(auth_service=get_auth_service())
    asyncio.run(engine.dispose())
    get_settings.cache_clear()


def run(coro):
    return asyncio.run(coro)


def test_a_created_user_can_sign_in_with_its_roles(store):
    user = run(store.create_user("Dana", PASSWORD, ["developer"]))
    assert user.username == "dana" and user.roles == ["developer"]
    signed_in = run(store.authenticate("dana", PASSWORD))
    assert signed_in is not None and signed_in.roles == ["developer"]
    assert run(store.authenticate("dana", "wrong-password-xx")) is None


@pytest.mark.parametrize(
    "username, roles, password, message",
    [
        ("Bad Name", ["viewer"], PASSWORD, "Invalid user name"),
        ("ok", ["superuser"], PASSWORD, "Unknown role"),
        ("ok", [], PASSWORD, "Unknown role"),
        ("ok", ["viewer"], "short", "at least"),
        ("ok-user", ["viewer"], "ok-user", "at least"),
    ],
)
def test_invalid_requests_say_why(store, username, roles, password, message):
    with pytest.raises(UserAdminError, match=message):
        run(store.create_user(username, password, roles))


def test_a_name_cannot_be_taken_twice(store):
    run(store.create_user("dana", PASSWORD, ["viewer"]))
    with pytest.raises(UserAdminError, match="exists"):
        run(store.create_user("DANA", PASSWORD, ["viewer"]))


def test_roles_and_password_change(store):
    run(store.create_user("dana", PASSWORD, ["viewer"]))
    assert run(store.set_roles("dana", ["operator"])).roles == ["operator"]
    run(store.set_password("dana", "another-long-password"))
    assert run(store.authenticate("dana", PASSWORD)) is None
    assert run(store.authenticate("dana", "another-long-password")) is not None


def test_a_disabled_user_cannot_sign_in_and_can_be_enabled_again(store):
    run(store.create_user("dana", PASSWORD, ["viewer"]))
    run(store.set_active("dana", False))
    assert run(store.authenticate("dana", PASSWORD)) is None
    run(store.set_active("dana", True))
    assert run(store.authenticate("dana", PASSWORD)) is not None


def test_the_last_administrator_cannot_be_removed(store):
    run(store.create_user("root", PASSWORD, ["admin"]))
    with pytest.raises(UserAdminError, match="no administrator"):
        run(store.set_active("root", False))
    with pytest.raises(UserAdminError, match="no administrator"):
        run(store.set_roles("root", ["viewer"]))
    run(store.create_user("second", PASSWORD, ["admin"]))
    run(store.set_active("root", False))  # another administrator remains


def test_an_unknown_user_is_named(store):
    with pytest.raises(UserAdminError, match="No user called 'ghost'"):
        run(store.set_active("ghost", False))


def test_list_is_sorted(store):
    run(store.create_user("zed", PASSWORD, ["viewer"]))
    run(store.create_user("amy", PASSWORD, ["operator"]))
    assert [u.username for u in run(store.list_users())] == ["amy", "zed"]


@pytest.fixture
def fresh_db_state(monkeypatch):
    """No engine, session factory or migration flag left by an earlier test."""
    monkeypatch.setattr(db_engine, "_engine", None, raising=False)
    monkeypatch.setattr(db_session, "_session_factory", None, raising=False)
    monkeypatch.setattr("ducta_server.db.migrate._migrations_run", False, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("fresh_db_state")
class TestCommand:
    def test_the_whole_cycle_through_the_command(self, tmp_path, monkeypatch, capsys):
        from ducta_server.cli import main

        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("PW", PASSWORD)
        db = str(tmp_path / "cli.db")

        def cmd(*args):
            return main(["user", "--db", db, *args])

        assert cmd("add", "dana", "--role", "developer", "--password-env", "PW") == 0
        assert cmd("add", "root", "--role", "admin", "--password-env", "PW") == 0
        assert cmd("list") == 0
        out = capsys.readouterr().out
        assert "dana" in out and "developer" in out and "active" in out
        assert cmd("set-role", "dana", "operator") == 0
        assert cmd("disable", "dana") == 0
        assert "disabled" in capsys.readouterr().out
        assert cmd("disable", "root") == 2  # the last administrator
        assert "no administrator" in capsys.readouterr().err

    def test_without_a_terminal_the_password_comes_from_the_environment(
        self, tmp_path, monkeypatch
    ):
        from ducta_server.cli import main

        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
        with pytest.raises(SystemExit, match="--password-env"):
            main(["user", "--db", str(tmp_path / "c.db"), "add", "dana"])

    def test_starting_the_server_is_unchanged(self):
        from ducta_server.cli import build_parser

        assert build_parser().parse_args(["--port", "9000", "--no-browser"]).port == 9000
