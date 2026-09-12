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

Shared bootstrap for the ``node_worker.py`` / ``sweep_worker.py``
multiprocessing entry points: both build an isolated pipeline ``Context`` in
a fresh worker process, from a picklable payload dict, optionally silencing
stdout/stderr. Extracted because both previously carried independent
~25-line copies of this exact sequence.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any, Dict, Tuple


@contextlib.contextmanager
def silence_output(quiet: bool):
    """Redirect stdout/stderr to ``os.devnull`` for the block's duration, when *quiet*."""
    if not quiet:
        yield
        return
    with open(os.devnull, "w") as devnull:
        with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
            yield


def bootstrap_worker_context(
    payload: Dict[str, Any], *, ensure_output_dir: bool = False
) -> Tuple[Any, Any]:
    """Build a ``(config_manager, context)`` pair for a worker-process payload."""
    from ducta.console.config import ConfigManager
    from ducta.console.execution import ContextInitializer

    config_manager = ConfigManager(
        base_path=payload.get("base_path"),
        layer_name=payload.get("layer_name"),
        use_case=payload.get("use_case_name"),
        config_type=payload.get("config_type"),
        interactive=False,
        require_config=False,
    )
    config_manager.change_to_config_directory()
    context = ContextInitializer(config_manager).initialize(payload["env"])

    output_path = payload.get("output_path")
    if output_path:
        if ensure_output_dir:
            os.makedirs(output_path, exist_ok=True)
        context.output_path = output_path
        settings = getattr(context, "global_config", None)
        if isinstance(settings, dict):
            settings["output_path"] = output_path

    return config_manager, context
