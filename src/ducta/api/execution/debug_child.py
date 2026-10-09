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

The process a debug run executes in: started by the API under debugpy
(``python -m debugpy --listen … --wait-for-client -m ducta.api.execution.debug_child``),
it runs the pipeline exactly as the API would — same context, scope and
sample — so a breakpoint can stop every thread without stopping the server.

Usage: ``debug_child <spec.json> <result.json>``. Writes the run's outcome and
certificate run id to *result.json*; exits non-zero when the run fails.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list) -> int:
    from ducta.api.execution.runner import (
        RunSpec,
        _dispatch_pipeline_type,
        _resolve_execution_context,
        normalize_execution_context_paths,
        redirect_to_scratch,
        select_execution_cwd,
    )

    raw = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    result_path = Path(argv[2])
    spec = RunSpec(**{**raw, "source_path": Path(raw["source_path"]), "debug": False})
    source_path = spec.source_path
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))
    ctx, env_dir = _resolve_execution_context(source_path, spec.env, spec.pipeline_name, None)
    gs = getattr(ctx, "global_config", None)
    if isinstance(gs, dict):
        gs["pipeline_name"] = spec.pipeline_name
        if spec.project_id:
            gs["project_id"] = spec.project_id
    cwd = select_execution_cwd(source_path, env_dir, ctx)
    os.chdir(cwd)
    normalize_execution_context_paths(ctx, cwd)
    if spec.sample_rows:
        redirect_to_scratch(ctx, spec.env, int(spec.sample_rows))

    from ducta.core.executors import PipelineExecutor
    from ducta.stream.constants import PipelineType

    engine = PipelineExecutor(ctx)
    pipeline = engine.batch_executor._get_pipeline_config(spec.pipeline_name)
    outcome = None
    error = None
    try:
        outcome = _dispatch_pipeline_type(
            engine, pipeline.get("type", PipelineType.BATCH.value), spec, ctx
        )
    except Exception as e:  # noqa: BLE001 — reported to the parent, which fails the run
        error = f"{type(e).__name__}: {e}"
        raise
    finally:
        result_path.write_text(
            json.dumps(
                {
                    "outcome": outcome,
                    "error": error,
                    "certificate_run_id": getattr(ctx, "_run_id", None),
                },
                default=str,
            ),
            encoding="utf-8",
        )
        try:
            engine.shutdown()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
