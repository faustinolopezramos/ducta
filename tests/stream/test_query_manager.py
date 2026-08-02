"""Unit tests for checkpoint-path handling in StreamingQueryManager (traversal-safe)."""

from __future__ import annotations

from ducta.stream.query_manager import StreamingQueryManager as QM


class TestSanitizePathComponent:
    def test_separators_replaced(self):
        assert QM._sanitize_path_component("a/b") == "a_b"
        assert QM._sanitize_path_component("a\\b") == "a_b"

    def test_parent_traversal_neutralized(self):
        # leading dots/slashes stripped -> no traversal possible
        assert ".." not in QM._sanitize_path_component("../etc")
        assert "/" not in QM._sanitize_path_component("../../root")

    def test_empty_becomes_placeholder(self):
        assert QM._sanitize_path_component("") == "_unnamed"
        assert QM._sanitize_path_component("...") == "_unnamed"

    def test_unicode_control_chars_removed(self):
        # bidi override (Cf) and null (Cc) stripped
        assert QM._sanitize_path_component("a‮b\x00c") == "abc"


class TestIsCloudPath:
    def test_cloud_schemes(self):
        assert QM._is_cloud_path("s3://bucket/x")
        assert QM._is_cloud_path("abfss://c@a/x")

    def test_local_path(self):
        assert not QM._is_cloud_path("/local/dir")


class TestBuildCheckpointPath:
    def _qm(self):
        # bypass __init__ (needs a context/Spark) — the method uses only static helpers
        return QM.__new__(QM)

    def test_local_composition(self):
        qm = self._qm()
        path = qm._build_checkpoint_path("/base/ck", "pipe", "node", "exec123")
        assert path.endswith("pipe/node/exec123")
        assert path.startswith("/base/ck")

    def test_sanitizes_components(self):
        qm = self._qm()
        path = qm._build_checkpoint_path("/base", "../evil", "n/ode", "e1")
        assert "../" not in path

    def test_cloud_composition(self):
        qm = self._qm()
        path = qm._build_checkpoint_path("s3://b/ck", "pipe", "node", "e1")
        assert path == "s3://b/ck/pipe/node/e1"
