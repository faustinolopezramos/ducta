"""Unit tests for ducta.check.output_manager.QualityOutputManager."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ducta.check.output_manager import QualityOutputManager


def _manager():
    # WriterFactory construction is irrelevant to _resolve_output_path (which
    # only touches self.context when base_path is falsy, not exercised here);
    # patch it out to avoid depending on a fully-configured context.
    with patch("ducta.check.output_manager.WriterFactory"):
        return QualityOutputManager(SimpleNamespace())


class TestResolveOutputPath:
    def test_sanitizes_node_name(self, tmp_path):
        """Regression: node_name/run_id/report_type must not be able to escape
        base_path via path separators or '..' components."""
        manager = _manager()
        path = manager._resolve_output_path(str(tmp_path), "../../etc", "run1", "dq")
        assert ".." not in Path(path).parts

    def test_normal_inputs_still_produce_expected_layout(self, tmp_path):
        manager = _manager()
        path = manager._resolve_output_path(
            str(tmp_path), "my_node", "run1", "dq", pipeline_name="my_pipeline"
        )
        assert path == str(Path(str(tmp_path)) / "dq" / "my_pipeline" / "my_node" / "run1")

    def test_default_pipeline_name_is_adhoc(self, tmp_path):
        manager = _manager()
        path = manager._resolve_output_path(str(tmp_path), "my_node", "run1", "dq")
        assert path == str(Path(str(tmp_path)) / "dq" / "_adhoc" / "my_node" / "run1")

    def test_different_pipelines_produce_different_paths(self, tmp_path):
        """Regression: two pipelines with a same-named node/run_id must not collide."""
        manager = _manager()
        path_a = manager._resolve_output_path(
            str(tmp_path), "my_node", "run1", "dq", pipeline_name="pipe_a"
        )
        path_b = manager._resolve_output_path(
            str(tmp_path), "my_node", "run1", "dq", pipeline_name="pipe_b"
        )
        assert path_a != path_b
