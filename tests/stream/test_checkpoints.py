"""Unit tests for ducta.stream.checkpoints.CheckpointManager.

There was previously no dedicated test file for this collaborator (extracted
from StreamingQueryManager) — these tests cover checkpoint-base resolution
(including dict-style context), path building, and reservation bookkeeping.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from ducta.stream.checkpoints import CheckpointManager
from ducta.stream.exceptions import StreamingConfigurationError


class TestDetermineCheckpointBase:
    def test_explicit_base_checkpoint_wins(self, dict_context):
        manager = CheckpointManager(dict_context)
        assert manager.determine_checkpoint_base("explicit/base") == "explicit/base"

    def test_falls_back_to_global_settings_with_dict_context(self, dict_context):
        # Regression: determine_checkpoint_base must resolve global_settings
        # from a plain dict context, not only from an attribute-based object.
        manager = CheckpointManager(dict_context)
        assert manager.determine_checkpoint_base(None) == "/tmp/checkpoints"

    def test_falls_back_to_global_settings_with_object_context(self, obj_context):
        manager = CheckpointManager(obj_context)
        assert manager.determine_checkpoint_base(None) == "/tmp/checkpoints"

    def test_falls_back_to_output_path_when_no_global_setting(self, dict_context):
        dict_context = dict(dict_context)
        dict_context["global_settings"] = {}
        manager = CheckpointManager(dict_context)
        assert manager.determine_checkpoint_base(None) == "/tmp/output/streaming_checkpoints"

    def test_raises_when_nothing_configured(self):
        manager = CheckpointManager({"global_settings": {}})
        with pytest.raises(StreamingConfigurationError):
            manager.determine_checkpoint_base(None)


class TestBuildCheckpointPath:
    def test_local_path_joins_components(self):
        path = CheckpointManager.build_checkpoint_path("/tmp/ckpt", "pipe", "node", "exec1")
        assert path == str(Path("/tmp/ckpt") / "pipe" / "node" / "exec1")

    def test_cloud_path_uses_forward_slashes(self):
        path = CheckpointManager.build_checkpoint_path("s3://bucket/ckpt", "pipe", "node", "exec1")
        assert path == "s3://bucket/ckpt/pipe/node/exec1"

    def test_file_scheme_is_stripped_for_local_paths(self):
        # Regression: "file://" checkpoint bases must be treated as local paths,
        # not produce a literal "file:" directory relative to the cwd.
        with_scheme = CheckpointManager.build_checkpoint_path(
            "file:///tmp/ckpt", "pipe", "node", "exec1"
        )
        without_scheme = CheckpointManager.build_checkpoint_path(
            "/tmp/ckpt", "pipe", "node", "exec1"
        )
        assert with_scheme == without_scheme

    def test_execution_id_is_sanitized(self):
        # Regression: execution_id must be sanitized like pipeline_name/node_name
        # so it can never introduce a path-traversal component.
        path = CheckpointManager.build_checkpoint_path("/tmp/ckpt", "pipe", "node", "../../etc")
        assert ".." not in path.split("/")


class TestValidateAndReserve:
    def test_reserves_new_path(self):
        manager = CheckpointManager({})
        lock = threading.Lock()
        manager.validate_and_reserve("/tmp/ckpt/a", "node_a", {}, lock)
        assert "/tmp/ckpt/a" in manager._reserved_checkpoints

    def test_rejects_already_reserved_path(self):
        manager = CheckpointManager({})
        lock = threading.Lock()
        manager.validate_and_reserve("/tmp/ckpt/a", "node_a", {}, lock)
        with pytest.raises(StreamingConfigurationError, match="already reserved"):
            manager.validate_and_reserve("/tmp/ckpt/a", "node_b", {}, lock)

    def test_rejects_path_in_use_by_active_query(self):
        manager = CheckpointManager({})
        lock = threading.Lock()
        active_queries = {
            "pipe:exec1:node_a": {"resolved_checkpoint": "/tmp/ckpt/a", "node_name": "node_a"}
        }
        with pytest.raises(StreamingConfigurationError, match="already in use"):
            manager.validate_and_reserve("/tmp/ckpt/a", "node_b", active_queries, lock)

    def test_release_then_reserve_again_succeeds(self):
        manager = CheckpointManager({})
        lock = threading.Lock()
        manager.validate_and_reserve("/tmp/ckpt/a", "node_a", {}, lock)
        manager.release_reservation("/tmp/ckpt/a", lock)
        # Should not raise now that the reservation was released.
        manager.validate_and_reserve("/tmp/ckpt/a", "node_b", {}, lock)

    def test_discard_reservation_removes_it(self):
        manager = CheckpointManager({})
        lock = threading.Lock()
        manager.validate_and_reserve("/tmp/ckpt/a", "node_a", {}, lock)
        manager.discard_reservation("/tmp/ckpt/a")
        assert "/tmp/ckpt/a" not in manager._reserved_checkpoints
