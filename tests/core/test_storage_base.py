"""Unit tests for ducta.core.storage.base.LocalStorageBackend."""

from __future__ import annotations

import pytest

from ducta.core.storage.base import LocalStorageBackend


class TestPathContainment:
    def test_normal_key_resolves_inside_root(self, tmp_path):
        backend = LocalStorageBackend(root_dir=tmp_path / "storage")
        backend.put_object("a/b.txt", b"hello")
        assert backend.get_object("a/b.txt") == b"hello"

    def test_sibling_directory_escape_is_rejected(self, tmp_path):
        # A sibling directory whose name starts with the same characters as the
        # storage root (e.g. "storage_evil" vs "storage") must not be reachable
        # via "../storage_evil" — a naive str.startswith() containment check
        # would incorrectly allow this.
        (tmp_path / "storage_evil").mkdir()
        backend = LocalStorageBackend(root_dir=tmp_path / "storage")
        with pytest.raises(ValueError, match="Path traversal detected"):
            backend.put_object("../storage_evil/x.txt", b"evil")

    def test_parent_traversal_is_rejected(self, tmp_path):
        backend = LocalStorageBackend(root_dir=tmp_path / "storage")
        with pytest.raises(ValueError, match="Path traversal detected"):
            backend.get_object("../secret.txt")

    def test_exact_root_key_is_allowed(self, tmp_path):
        # target == root_dir itself must not be rejected by the containment check.
        backend = LocalStorageBackend(root_dir=tmp_path / "storage")
        assert backend.list_objects("") == []
