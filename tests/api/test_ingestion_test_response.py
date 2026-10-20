"""The connection-test endpoints say what happened: verified, failed, or not tested.

The messages used to be swapped — a refused connection read "inconclusive
(Spark unavailable)", and one nobody had contacted read "verified" with ok=True.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from ducta.api.routes.ingestion import _test_response  # noqa: E402


def test_verified():
    r = _test_response(True)
    assert r.ok is True and "verified" in r.message.lower()


def test_failed_says_failed():
    r = _test_response(False)
    assert r.ok is False and "failed" in r.message.lower()


def test_untested_is_not_ok():
    r = _test_response(None)
    assert r.ok is False and r.message.startswith("Not verified")
