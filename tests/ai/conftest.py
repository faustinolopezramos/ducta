"""Shared set-up for the AI tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_retry_waits(monkeypatch):
    """A provider's retry waits (rate limits, overload) take no time in tests."""
    from ducta.ai.providers import OpenAICompatibleProvider

    monkeypatch.setattr(OpenAICompatibleProvider, "_sleep", staticmethod(lambda seconds: None))
