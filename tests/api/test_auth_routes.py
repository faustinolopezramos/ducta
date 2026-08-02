"""Regression tests for ducta.api.routes.auth's TLS-aware Secure cookie flag.

`secure=settings.environment == "production"` didn't reflect whether *this*
particular connection was actually HTTPS — a production server behind a
plain-HTTP internal load balancer would still mark the cookie Secure, and a
real browser silently drops a Secure cookie set over plain HTTP.
"""

from __future__ import annotations

from types import SimpleNamespace

from ducta.api.routes.auth import _is_tls_request


def _request(scheme="http", client_host=None, forwarded_proto=None):
    headers = {"x-forwarded-proto": forwarded_proto} if forwarded_proto else {}
    return SimpleNamespace(
        url=SimpleNamespace(scheme=scheme),
        client=SimpleNamespace(host=client_host) if client_host else None,
        headers=headers,
    )


class TestIsTlsRequest:
    def test_direct_https_is_tls(self):
        assert _is_tls_request(_request(scheme="https")) is True

    def test_direct_http_is_not_tls(self):
        assert _is_tls_request(_request(scheme="http")) is False

    def test_forwarded_proto_from_loopback_proxy_is_trusted(self):
        req = _request(scheme="http", client_host="127.0.0.1", forwarded_proto="https")
        assert _is_tls_request(req) is True

    def test_forwarded_proto_from_private_proxy_is_trusted(self):
        req = _request(scheme="http", client_host="10.0.0.5", forwarded_proto="https")
        assert _is_tls_request(req) is True

    def test_forwarded_proto_from_untrusted_public_peer_is_ignored(self):
        # A direct public-internet client claiming X-Forwarded-Proto: https
        # must not be trusted — that header is meant to come from a proxy.
        req = _request(scheme="http", client_host="8.8.8.8", forwarded_proto="https")
        assert _is_tls_request(req) is False

    def test_forwarded_proto_http_from_proxy_is_not_tls(self):
        req = _request(scheme="http", client_host="127.0.0.1", forwarded_proto="http")
        assert _is_tls_request(req) is False
