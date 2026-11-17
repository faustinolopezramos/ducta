"""`ducta ui` / `ducta server start` on an address beyond this machine.

The API runs pipelines: reaching it is reaching code execution. `--host 0.0.0.0` used to
serve without authentication and without a word, because the API's exposure warning reads
HOST from the environment and `launch_ui` never set it.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from ducta.console.core import ExitCode
from ducta_server.launcher import launch_ui


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    # Restored on teardown whatever launch_ui sets.
    for name in ("HOST", "AUTH_ENABLED", "DATABASE_URL", "DUCTA_WORKSPACE"):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    monkeypatch.setenv("DATABASE_URL", "")  # no history database for these tests
    from ducta_server.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _launch(host, **kwargs):
    run = MagicMock()
    with patch("uvicorn.run", run):
        code = launch_ui(host=host, open_browser=False, **kwargs)
    return code, run


def test_a_non_local_host_without_authentication_is_refused():
    code, run = _launch("0.0.0.0")
    assert code == ExitCode.SECURITY_ERROR.value
    run.assert_not_called()


def test_an_empty_host_is_every_interface_and_is_refused():
    # uvicorn binds host="" to INADDR_ANY: as open as 0.0.0.0.
    code, run = _launch("")
    assert code == ExitCode.SECURITY_ERROR.value
    run.assert_not_called()


def test_loopback_hosts_are_served_as_before():
    for host in ("127.0.0.1", "localhost", "::1"):
        code, run = _launch(host)
        assert code == 0
        run.assert_called_once()


def test_authentication_on_allows_a_non_local_host(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    monkeypatch.setenv("DUCTA_ADMIN_PASSWORD", "a-password-of-my-own")
    code, run = _launch("0.0.0.0")
    assert code == 0
    run.assert_called_once()


@pytest.mark.parametrize("secret, password", [(None, "own-password"), ("x" * 40, None)])
def test_authentication_with_default_credentials_is_refused_on_a_non_local_host(
    monkeypatch, secret, password
):
    # Accounts on, but the JWT key or the admin password is the published default: anyone
    # can sign a token as admin / log in as admin:admin. Loopback is still fine.
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("DUCTA_ADMIN_PASSWORD", raising=False)
    if secret:
        monkeypatch.setenv("JWT_SECRET_KEY", secret)
    if password:
        monkeypatch.setenv("DUCTA_ADMIN_PASSWORD", password)
    code, run = _launch("0.0.0.0")
    assert code == ExitCode.SECURITY_ERROR.value
    run.assert_not_called()
    code, run = _launch("127.0.0.1")
    assert code == 0
    run.assert_called_once()


def test_the_flag_allows_it_loudly():
    with patch("ducta_server.launcher.logger") as log:
        code, run = _launch("0.0.0.0", allow_unauthenticated=True)
    assert code == 0
    run.assert_called_once()
    assert "WITHOUT authentication" in str(log.warning.call_args)


def test_the_api_sees_the_address_it_is_bound_to():
    _launch("127.0.0.1")
    assert os.environ["HOST"] == "127.0.0.1"
    _launch("0.0.0.0", allow_unauthenticated=True)
    assert os.environ["HOST"] == "0.0.0.0"


def test_both_commands_know_the_flag_and_the_terminal_flag_is_gone():
    from ducta.console.parser import UnifiedArgumentParser

    root = UnifiedArgumentParser.create()
    for argv in (["ui", "--allow-unauthenticated"], ["server", "start", "--allow-unauthenticated"]):
        assert root.parse_args(argv).allow_unauthenticated is True
    with pytest.raises(SystemExit):
        root.parse_args(["ui", "--enable-terminal"])


def test_ducta_server_takes_the_same_options():
    from ducta_server.cli import build_parser

    args = build_parser().parse_args(["--allow-unauthenticated", "--db", "x.db", "--port", "9"])
    assert (args.allow_unauthenticated, args.db_path, args.port) == (True, "x.db", 9)
