"""Regression tests for `maybe_write_audit`.

It used to bail out whenever `request.state.current_user` was unset — which
is exactly the case for a failed login or a 401/403 raised by
`get_current_user`/`require_permission` — so the audit trail only ever
recorded requests that *succeeded*. Failed login attempts and
rejected/forbidden requests left no trace at all.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ducta.api.middleware.audit import maybe_write_audit


def _request(method="POST", path="/api/projects/x", current_user=None, json_body=None):
    req = SimpleNamespace()
    req.method = method
    req.url = SimpleNamespace(path=path)
    req.state = SimpleNamespace()
    if current_user is not None:
        req.state.current_user = current_user
    req.state.source_path = None
    req.json = AsyncMock(return_value=json_body)
    return req


def _response(status_code=200):
    return SimpleNamespace(status_code=status_code)


def _settings(auth_enabled=True):
    return SimpleNamespace(auth_enabled=auth_enabled)


class TestMaybeWriteAuditSuccessfulRequest:
    def test_still_logs_successful_authenticated_request(self):
        user = SimpleNamespace(id="u1", username="alice")
        req = _request(current_user=user)
        resp = _response(200)

        with patch("ducta.api.utils.audit.write_audit_entry") as mock_write:
            asyncio.run(maybe_write_audit(req, resp, _settings(), "req-1"))

        mock_write.assert_called_once()
        _, kwargs = mock_write.call_args
        assert kwargs["user_id"] == "u1"
        assert kwargs["username"] == "alice"
        assert kwargs["status_code"] == 200


class TestMaybeWriteAuditFailedLogin:
    def test_logs_failed_login_with_username_attempted(self):
        req = _request(
            method="POST",
            path="/api/auth/login",
            json_body={"username": "bob", "password": "secret"},
        )
        resp = _response(401)

        with patch("ducta.api.utils.audit.write_audit_entry") as mock_write:
            asyncio.run(maybe_write_audit(req, resp, _settings(), "req-2"))

        mock_write.assert_called_once()
        _, kwargs = mock_write.call_args
        assert kwargs["user_id"] == "anonymous"
        assert kwargs["username"] == "unknown"
        assert kwargs["username_attempted"] == "bob"
        assert "password" not in json.dumps(kwargs)
        assert kwargs["status_code"] == 401


class TestMaybeWriteAuditRejectedRequest:
    def test_logs_403_forbidden_request_without_user(self):
        req = _request(method="DELETE", path="/api/projects/x")
        resp = _response(403)

        with patch("ducta.api.utils.audit.write_audit_entry") as mock_write:
            asyncio.run(maybe_write_audit(req, resp, _settings(), "req-3"))

        mock_write.assert_called_once()
        _, kwargs = mock_write.call_args
        assert kwargs["user_id"] == "anonymous"
        assert kwargs["status_code"] == 403

    def test_does_not_log_unauthenticated_success(self):
        # No user, no 401/403 — nothing meaningful to attribute.
        req = _request(method="POST", path="/api/health-ish")
        resp = _response(200)

        with patch("ducta.api.utils.audit.write_audit_entry") as mock_write:
            asyncio.run(maybe_write_audit(req, resp, _settings(), "req-4"))

        mock_write.assert_not_called()

    def test_does_not_log_when_auth_disabled(self):
        user = SimpleNamespace(id="u1", username="alice")
        req = _request(current_user=user)
        resp = _response(200)

        with patch("ducta.api.utils.audit.write_audit_entry") as mock_write:
            asyncio.run(maybe_write_audit(req, resp, _settings(auth_enabled=False), "req-5"))

        mock_write.assert_not_called()
