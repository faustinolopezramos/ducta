"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0
"""

import re
import threading
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional, Set

from loguru import logger  # type: ignore

from ducta.stream.context_utils import get_context_value
from ducta.stream.exceptions import StreamingConfigurationError, StreamingError


class CheckpointManager:
    """Resolves, sanitizes, and reserves streaming checkpoint locations.

    Extracted from StreamingQueryManager (composition, not inheritance) so
    checkpoint path logic can be tested and reasoned about in isolation.
    Reservation state (`_reserved_checkpoints`) is owned here, but the lock
    guarding it is shared with the caller's active-queries lock (passed in per
    call) — the original implementation used a single lock for both active
    queries and checkpoint reservations, and that must not change.
    """

    def __init__(self, context: Any):
        self.context = context
        self._reserved_checkpoints: Set[str] = set()

    @staticmethod
    def is_cloud_path(path: str) -> bool:
        """Check if path is on a cloud filesystem."""
        return str(path).startswith(("s3://", "gs://", "abfs://", "abfss://", "hdfs://", "dbfs:/"))

    @staticmethod
    def sanitize_path_component(component: str) -> str:
        """Sanitize a user-supplied path component to prevent directory traversal."""
        s = str(component)
        # Remove Unicode control (Cc) and format (Cf) characters, which include
        # bidirectional override codepoints that can spoof file paths in terminals.
        s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf"))
        # Replace path-separator characters and colons with underscores.
        sanitized = re.sub(r"[/\\:]+", "_", s).strip("_. ")
        return sanitized if sanitized else "_unnamed"

    def determine_checkpoint_base(self, base_checkpoint: Optional[str]) -> str:
        """Determine the base directory for checkpoints."""
        if base_checkpoint:
            return base_checkpoint

        checkpoints_base = None
        try:
            gs = get_context_value(self.context, "global_config", {}) or {}
            if isinstance(gs, dict):
                checkpoints_base = gs.get("checkpoints_base")
        except Exception as e:
            logger.debug(f"Could not read global_config.checkpoints_base: {e}")
            checkpoints_base = None

        if checkpoints_base:
            return str(checkpoints_base)

        output_path = get_context_value(self.context, "output_path", None)
        if output_path is None:
            raise StreamingConfigurationError(
                "No checkpoint base directory is configured. "
                "Set one of: node 'streaming.checkpoint', "
                "global_config.checkpoints_base, or context.output_path. "
                "Falling back to a system temp directory is not allowed in production "
                "because checkpoints may be lost on OS restart.",
                config_section="streaming.checkpoint / global_config.checkpoints_base",
            )
        return str(Path(output_path) / "streaming_checkpoints")

    @staticmethod
    def build_checkpoint_path(
        checkpoint_base: str, pipeline_name: str, node_name: str, execution_id: str
    ) -> str:
        """Build the full checkpoint path from base and identifiers."""
        safe_pipeline = CheckpointManager.sanitize_path_component(pipeline_name)
        safe_node = CheckpointManager.sanitize_path_component(node_name)
        # execution_id is always caller-generated (uuid4().hex) today, but sanitize
        # it too for defense in depth — same reasoning as pipeline_name/node_name.
        safe_execution_id = CheckpointManager.sanitize_path_component(execution_id)
        if CheckpointManager.is_cloud_path(checkpoint_base):
            return f"{checkpoint_base.rstrip('/')}/{safe_pipeline}/{safe_node}/{safe_execution_id}"
        # A local checkpoint_base may be given as a file:// URI (Spark accepts
        # those for checkpointLocation); strip the scheme before handing it to
        # pathlib, which would otherwise treat "file:" as a literal directory name.
        local_base = (
            checkpoint_base[len("file://") :]
            if checkpoint_base.startswith("file://")
            else checkpoint_base
        )
        return str(Path(local_base) / safe_pipeline / safe_node / safe_execution_id)

    def ensure_checkpoint_dir(self, checkpoint_path: str) -> None:
        """Ensure checkpoint directory exists for local filesystems."""
        try:
            Path(checkpoint_path).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StreamingError(
                f"Cannot create checkpoint directory '{checkpoint_path}': {str(e)}",
                error_code="CHECKPOINT_CREATION_ERROR",
                context={"checkpoint_path": checkpoint_path},
                cause=e,
            ) from e

    def get_checkpoint_location(
        self, base_checkpoint: Optional[str], pipeline_name: str, node_name: str, execution_id: str
    ) -> str:
        """Get checkpoint location for the streaming query with validation."""
        try:
            checkpoint_base = self.determine_checkpoint_base(base_checkpoint)
            checkpoint_path = self.build_checkpoint_path(
                checkpoint_base, pipeline_name, node_name, execution_id
            )

            if not self.is_cloud_path(checkpoint_path):
                self.ensure_checkpoint_dir(checkpoint_path)

            return checkpoint_path

        except Exception as e:
            logger.error(f"Error setting up checkpoint location: {str(e)}")
            if isinstance(e, StreamingError):
                raise
            else:
                raise StreamingError(
                    f"Failed to setup checkpoint location: {str(e)}",
                    error_code="CHECKPOINT_SETUP_ERROR",
                    cause=e,
                ) from e

    def validate_and_reserve(
        self,
        checkpoint_path: str,
        node_name: str,
        active_queries: Dict[str, Dict[str, Any]],
        active_queries_lock: threading.Lock,
    ) -> None:
        """Atomically validate and reserve a checkpoint path to prevent concurrent-start races.

        `active_queries`/`active_queries_lock` belong to the caller (query
        lifecycle tracking); this method only inspects them to detect
        collisions and reuses the same lock so reservation state and active
        queries stay consistent under one critical section, exactly as before
        this class existed.
        """
        with active_queries_lock:
            for query_key, query_info in active_queries.items():
                existing_checkpoint = query_info.get("resolved_checkpoint")
                if existing_checkpoint and existing_checkpoint == checkpoint_path:
                    existing_node = query_info.get("node_name", "unknown")
                    raise StreamingConfigurationError(
                        f"Checkpoint location '{checkpoint_path}' is already in use by query '{existing_node}'. "
                        f"Each streaming query must have a unique checkpoint location.",
                        config_section="streaming.checkpoint_location",
                        config_value=checkpoint_path,
                        context={
                            "current_node": node_name,
                            "conflicting_node": existing_node,
                            "query_key": query_key,
                        },
                    )
            if checkpoint_path in self._reserved_checkpoints:
                raise StreamingConfigurationError(
                    f"Checkpoint location '{checkpoint_path}' is already reserved by another starting query. "
                    f"Each streaming query must have a unique checkpoint location.",
                    config_section="streaming.checkpoint_location",
                    config_value=checkpoint_path,
                    context={"current_node": node_name},
                )
            self._reserved_checkpoints.add(checkpoint_path)

    def release_reservation(
        self, checkpoint_path: str, active_queries_lock: threading.Lock
    ) -> None:
        """Release a reserved checkpoint when Spark startup fails before query registration."""
        with active_queries_lock:
            self._reserved_checkpoints.discard(checkpoint_path)

    def discard_reservation(self, checkpoint_path: str) -> None:
        """Drop a reservation once ownership has transferred to an active query.

        Caller (StreamingQueryManager.create_and_start_query) must already hold
        the active-queries lock when calling this — it performs no locking of
        its own, matching the original inline `self._reserved_checkpoints.discard(...)`.
        """
        self._reserved_checkpoints.discard(checkpoint_path)
