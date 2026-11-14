"""Wrong passwords are throttled: 25 of them used to be answered in four seconds."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ducta_server.auth.throttle import LoginThrottle, reset_login_throttle


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TestLoginThrottle:
    def _throttle(self, clock, **kw):
        return LoginThrottle(
            max_attempts=3, window_seconds=60, lockout_seconds=30, clock=clock, **kw
        )

    def test_locks_after_the_allowed_failures(self):
        clock = Clock()
        t = self._throttle(clock)
        for _ in range(2):
            t.record_failure("ip:1", "admin")
            assert t.retry_after("ip:1", "admin") == 0
        t.record_failure("ip:1", "admin")
        assert 0 < t.retry_after("ip:1", "admin") <= 31

    def test_the_lock_ends(self):
        clock = Clock()
        t = self._throttle(clock)
        for _ in range(3):
            t.record_failure("ip:1", "admin")
        clock.now += 31
        assert t.retry_after("ip:1", "admin") == 0
        t.record_failure("ip:1", "admin")  # a fresh count, not an instant relock
        assert t.retry_after("ip:1", "admin") == 0

    def test_another_address_or_user_is_not_affected(self):
        t = self._throttle(Clock())
        for _ in range(3):
            t.record_failure("ip:1", "admin")
        assert t.retry_after("ip:2", "admin") == 0  # cannot lock the real person out
        assert t.retry_after("ip:1", "someone_else") == 0

    def test_the_user_name_is_case_insensitive(self):
        t = self._throttle(Clock())
        for name in ("Admin", "ADMIN", "admin"):
            t.record_failure("ip:1", name)
        assert t.retry_after("ip:1", "aDmIn") > 0

    def test_old_failures_are_forgotten(self):
        clock = Clock()
        t = self._throttle(clock)
        t.record_failure("ip:1", "admin")
        t.record_failure("ip:1", "admin")
        clock.now += 61
        t.record_failure("ip:1", "admin")
        assert t.retry_after("ip:1", "admin") == 0

    def test_success_clears_the_count(self):
        t = self._throttle(Clock())
        t.record_failure("ip:1", "admin")
        t.record_failure("ip:1", "admin")
        t.record_success("ip:1", "admin")
        t.record_failure("ip:1", "admin")
        assert t.retry_after("ip:1", "admin") == 0

    def test_zero_turns_it_off(self):
        t = LoginThrottle(max_attempts=0)
        for _ in range(100):
            t.record_failure("ip:1", "admin")
        assert t.retry_after("ip:1", "admin") == 0

    def test_memory_is_bounded(self):
        t = self._throttle(Clock(), max_keys=50)
        for i in range(500):
            t.record_failure(f"ip:{i}", "admin")
        assert len(t._failures) <= 50


@pytest.fixture
def client(monkeypatch, tmp_path):
    from ducta_server.config import get_settings
    from ducta_server.main import create_app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("DUCTA_ADMIN_PASSWORD", "S3cure-pass-123!")
    monkeypatch.setenv("LOGIN_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    reset_login_throttle()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()
    reset_login_throttle()


def _login(client, password):
    return client.post("/api/auth/login", json={"username": "admin", "password": password})


def test_the_login_route_locks_out_guessing(client):
    assert [_login(client, f"wrong{i}").status_code for i in range(3)] == [401, 401, 401]
    blocked = _login(client, "wrong3")
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    # even the right password waits: the lock is on the guesser, not on the password
    assert _login(client, "S3cure-pass-123!").status_code == 429


def test_the_right_password_before_the_limit_works_and_resets(client):
    _login(client, "wrong")
    _login(client, "wrong")
    assert _login(client, "S3cure-pass-123!").status_code == 200
    assert [_login(client, "wrong").status_code for _ in range(2)] == [401, 401]
