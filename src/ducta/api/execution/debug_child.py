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
import sys
from pathlib import Path


def main(argv: list) -> int:
    from ducta.api.execution.child import prepare
    from ducta.api.execution.runner import _dispatch_pipeline_type

    raw = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    result_path = Path(argv[2])
    spec, ctx = prepare(raw)

    from ducta.console.ux.reporter import ConsoleReporter
    from ducta.core.executors import PipelineExecutor
    from ducta.reporting import set_reporter
    from ducta.stream.constants import PipelineType

    set_reporter(ConsoleReporter())  # the parent streams this process's output to the run log
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
                    "retrain": getattr(ctx, "_retrain", None),
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
