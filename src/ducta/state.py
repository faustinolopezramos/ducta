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

Where Ducta keeps its own state: the ``.ducta`` folders, decided in one place.

Each path used to be written by hand wherever it was needed — the certificates'
default twice in ``core`` and once more in ``setting``, the API's sample runs on
their own — and the CLI and the web app once looked for certificates in different
folders. Everything that reads or writes framework state takes its location from
here. The leading dot hides it (as ``.git`` or ``.venv``): it is Ducta's
bookkeeping, not the project's data.

Three roots:

* **per environment**, under the environment's output — templates the engine
  interpolates (``${output_path}/${environment}/.ducta/...``);
* **per project**, relative to its root — editor schemas, comments, the API's
  config lock and audit log;
* **per user**, ``~/.ducta`` (``DUCTA_HOME`` moves it) — what belongs to the
  machine, not to a project: AI settings and evals, the web app's history, caches.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

#: The folder name every root uses.
DIR_NAME = ".ducta"

# ── per environment: ${output_path}/${environment}/.ducta/… ──────────────────

_ENV_ROOT = "${output_path}/${environment}/" + DIR_NAME

#: Run certificates (``settings.run_certificate_dir``).
RUNS_DIR = f"{_ENV_ROOT}/runs"
#: Chain-state markers (``settings.chain.state_dir``).
CHAIN_STATE_DIR = f"{_ENV_ROOT}/chain_state"
#: Run-lock files (``settings.run_lock.dir``).
LOCKS_DIR = f"{_ENV_ROOT}/locks"
#: Streaming run journals (``settings.stream_journal_dir``).
STREAMS_DIR = f"{_ENV_ROOT}/streams"

# ── per project, relative to its root ─────────────────────────────────────────

#: JSON Schemas editors read for completion.
SCHEMA_DIR = f"{DIR_NAME}/schema"
#: Review comment threads, one JSON file each.
COMMENTS_DIR = f"{DIR_NAME}/comments"
#: The API's lock on configuration edits.
CONFIG_LOCK = f"{DIR_NAME}/config.lock"
#: The API's audit trail.
AUDIT_LOG = f"{DIR_NAME}/audit.log"

PathLike = Union[str, Path]


def under(root: PathLike, *parts: str) -> Path:
    """``<root>/.ducta/<parts…>``: framework state below any folder."""
    return Path(root).joinpath(DIR_NAME, *parts)


def ai_dir(project_root: PathLike, *parts: str) -> Path:
    """``<project>/.ducta/ai/<parts…>``: drafts, reviews, explanations, agent state, jobs."""
    return under(project_root, "ai", *parts)


def scratch_dir(output_root: PathLike, env: str) -> Path:
    """Where a sample run writes instead of the real outputs: ``<output>/<env>/.ducta/scratch``."""
    return under(Path(output_root) / env, "scratch")


# ── per user: ~/.ducta ─────────────────────────────────────────────────────────


def user_dir(*parts: str) -> Path:
    """``~/.ducta/<parts…>`` (or ``$DUCTA_HOME/<parts…>``): state of the machine."""
    home = os.environ.get("DUCTA_HOME")
    root = Path(home).expanduser() if home else Path.home() / DIR_NAME
    return root.joinpath(*parts)
