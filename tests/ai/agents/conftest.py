"""The agents' tests never reach the machine's real model: no ~/.ducta/ai.toml,
no DUCTA_AI_* override, no keychain."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_real_model(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("DUCTA_HOME", str(tmp_path_factory.mktemp("ducta-home")))
    for name in ("DUCTA_AI_PROVIDER", "DUCTA_AI_MODEL", "DUCTA_AI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("ducta.ai.secrets._keyring", lambda: None)
