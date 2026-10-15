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

Running a pipeline the way a person would: ``ducta start`` in a child process.

The agents never run a pipeline in their own process — a run changes the
working directory, ``sys.path`` and the process's output streams — and run
exactly the Ducta this process is (same interpreter), not whatever ``ducta``
is first on PATH.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

_ENTRY = (
    "import sys; from ducta.console.wrapper import main; sys.argv[0] = 'ducta'; sys.exit(main())"
)
#: The most of a run's output kept, from its end.
_TAIL = 6000


@dataclass
class RunOutcome:
    exit_code: int
    #: The end of what the run printed: where its error is.
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def locked(self) -> bool:
        return self.exit_code == 7  # ExitCode.LOCKED: nothing ran, retry later


def ducta_command(*args: str) -> List[str]:
    return [sys.executable, "-c", _ENTRY, *args]


def start_args(
    env: str,
    pipeline: str,
    *,
    nodes: Sequence[str] = (),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    reuse_upstream: bool = False,
) -> List[str]:
    args = ["start", "--env", env, "--pipeline", pipeline]
    if len(nodes) == 1:
        args += ["--node", nodes[0]]
    if reuse_upstream:
        args.append("--reuse-upstream")
    if start_date:
        args += ["--start-date", start_date]
    if end_date:
        args += ["--end-date", end_date]
    return args


def run_pipeline(
    root: Path,
    env: str,
    pipeline: str,
    *,
    nodes: Sequence[str] = (),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    reuse_upstream: bool = False,
    timeout: Optional[float] = None,
) -> RunOutcome:
    """``ducta start`` for *pipeline* in *env*, from the project at *root*."""
    command = ducta_command(
        *start_args(
            env,
            pipeline,
            nodes=nodes,
            start_date=start_date,
            end_date=end_date,
            reuse_upstream=reuse_upstream,
        )
    )
    try:
        done = subprocess.run(
            command, cwd=str(root), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        return RunOutcome(124, (out + f"\nTimed out after {timeout:.0f}s")[-_TAIL:])
    except OSError as e:
        return RunOutcome(127, str(e))
    return RunOutcome(done.returncode, ((done.stdout or "") + (done.stderr or ""))[-_TAIL:])
