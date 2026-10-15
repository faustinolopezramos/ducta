"""List settings read from one environment variable, as JSON or comma-separated.

Only JSON parsed: `CORS_ORIGINS=https://ducta.company.com`, as docker-compose files
and the deployment guide write it, stopped the server at startup.
"""

from __future__ import annotations

import pytest

from ducta.api.config import Settings


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://ducta.company.com", ["https://ducta.company.com"]),
        ("https://a.com, https://b.com,", ["https://a.com", "https://b.com"]),
        ('["https://json.com"]', ["https://json.com"]),
    ],
)
def test_cors_origins(monkeypatch, raw, expected):
    monkeypatch.setenv("CORS_ORIGINS", raw)
    assert Settings(_env_file=None).cors_origins == expected


def test_git_clone_allowed_hosts_comma_separated(monkeypatch):
    monkeypatch.setenv("GIT_CLONE_ALLOWED_HOSTS", "dev.azure.com,github.com")
    assert Settings(_env_file=None).git_clone_allowed_hosts == ["dev.azure.com", "github.com"]


def test_defaults_are_untouched(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert "http://localhost:5173" in Settings(_env_file=None).cors_origins
