"""The certificate's copy to the StorageBackend is made only when one is configured.

Unconfigured, it went to ``~/.ducta/storage/certificates`` on every run of every project,
never pruned (2,921 folders on one machine), and the test suite added to it.
"""

from __future__ import annotations

import pytest

from ducta.core import storage as storage_pkg
from ducta.core.certificate import write_certificate
from ducta.core.storage import base as storage_base
from tests.core.test_certificate import _make_cert


@pytest.fixture
def fresh_backend(monkeypatch):
    """No cached StorageBackend: each test builds its own from the environment."""
    monkeypatch.setattr(storage_base, "_storage_instance", None)
    yield
    storage_base._storage_instance = None


def test_no_copy_without_a_configured_backend(tmp_path, monkeypatch, fresh_backend):
    monkeypatch.delenv("DUCTA_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("DUCTA_STORAGE_PATH", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    called = []
    monkeypatch.setattr(storage_pkg, "get_storage_backend", lambda *a: called.append(a))

    path = write_certificate(_make_cert(), tmp_path / "run")

    assert path.is_file()
    assert called == []
    assert not (home / ".ducta").exists()


def test_a_configured_path_gets_the_copy(tmp_path, monkeypatch, fresh_backend):
    monkeypatch.delenv("DUCTA_STORAGE_BACKEND", raising=False)
    store = tmp_path / "store"
    monkeypatch.setenv("DUCTA_STORAGE_PATH", str(store))

    write_certificate(_make_cert(run_id="run-42"), tmp_path / "run")

    assert (store / "certificates" / "run-42" / "certificate.json").is_file()
