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

    def test_falls_back_to_global_config_with_dict_context(self, dict_context):
        # Regression: determine_checkpoint_base must resolve global_config
        # from a plain dict context, not only from an attribute-based object.
        # dict_context has no env/environment, so it falls back to "base"
        # (Ducta storage convention — see determine_checkpoint_base).
        manager = CheckpointManager(dict_context)
        assert manager.determine_checkpoint_base(None) == "/tmp/checkpoints/base"

    def test_falls_back_to_global_config_with_object_context(self, obj_context):
        # obj_context.env == "test".
        manager = CheckpointManager(obj_context)
        assert manager.determine_checkpoint_base(None) == "/tmp/checkpoints/test"

    def test_falls_back_to_output_path_when_no_global_setting(self, dict_context):
        dict_context = dict(dict_context)
        dict_context["global_config"] = {}
        manager = CheckpointManager(dict_context)
        assert manager.determine_checkpoint_base(None) == "/tmp/output/base/streaming_checkpoints"

    def test_raises_when_nothing_configured(self):
        manager = CheckpointManager({"global_config": {}})
        with pytest.raises(StreamingConfigurationError):
            manager.determine_checkpoint_base(None)


class TestDetermineCheckpointBaseIsEnvScoped:
    """Ducta storage convention: a checkpoints_base/output_path fallback must
    never let two environments collide in the same checkpoint directory —
    same rule CoreSettings._resolve_scoped_dir applies to run_certificate_dir
    and chain_state_dir. See tests/core/test_chain_state_per_env.py.
    """

    def test_two_environments_get_different_bases_from_checkpoints_base(self, dict_context):
        dev_context = dict(dict_context)
        dev_context["env"] = "dev"
        prod_context = dict(dict_context)
        prod_context["env"] = "prod"

        dev = CheckpointManager(dev_context).determine_checkpoint_base(None)
        prod = CheckpointManager(prod_context).determine_checkpoint_base(None)

        assert dev == "/tmp/checkpoints/dev"
        assert prod == "/tmp/checkpoints/prod"

    def test_two_environments_get_different_bases_from_output_path_fallback(self, dict_context):
        dict_context = dict(dict_context)
        dict_context["global_config"] = {}

        dev_context = dict(dict_context)
        dev_context["env"] = "dev"
        prod_context = dict(dict_context)
        prod_context["env"] = "prod"

        dev = CheckpointManager(dev_context).determine_checkpoint_base(None)
        prod = CheckpointManager(prod_context).determine_checkpoint_base(None)

        assert dev == "/tmp/output/dev/streaming_checkpoints"
        assert prod == "/tmp/output/prod/streaming_checkpoints"

    def test_checkpoints_base_already_referencing_environment_is_not_double_scoped(
        self, dict_context
    ):
        dict_context = dict(dict_context)
        dict_context["env"] = "dev"
        dict_context["global_config"] = {
            "checkpoints_base": "${output_path}/${environment}/_checkpoints",
        }

        manager = CheckpointManager(dict_context)

        assert manager.determine_checkpoint_base(None) == "/tmp/output/dev/_checkpoints"


class TestBuildCheckpointPath:
    def test_local_path_joins_components(self):
        path = CheckpointManager.build_checkpoint_path("/tmp/ckpt", "pipe", "node")
        assert path == str(Path("/tmp/ckpt") / "pipe" / "node")

    def test_cloud_path_uses_forward_slashes(self):
        path = CheckpointManager.build_checkpoint_path("s3://bucket/ckpt", "pipe", "node")
        assert path == "s3://bucket/ckpt/pipe/node"

    def test_file_scheme_is_stripped_for_local_paths(self):
        # Regression: "file://" checkpoint bases must be treated as local paths,
        # not produce a literal "file:" directory relative to the cwd.
        with_scheme = CheckpointManager.build_checkpoint_path("file:///tmp/ckpt", "pipe", "node")
        without_scheme = CheckpointManager.build_checkpoint_path("/tmp/ckpt", "pipe", "node")
        assert with_scheme == without_scheme

    def test_is_deterministic_across_calls(self):
        # Regression: the path used to end in a fresh uuid4().hex per call, so
        # no streaming query could ever resume from a prior run's checkpoint.
        first = CheckpointManager.build_checkpoint_path("/tmp/ckpt", "pipe", "node")
        second = CheckpointManager.build_checkpoint_path("/tmp/ckpt", "pipe", "node")
        assert first == second

    def test_pipeline_and_node_names_are_sanitized(self):
        # Regression: pipeline_name/node_name must be sanitized so they can
        # never introduce a path-traversal component.
        path = CheckpointManager.build_checkpoint_path("/tmp/ckpt", "../../etc", "node")
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
