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

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

DIR_NAME = ".ducta"
_ENV_ROOT = "${output_path}/${environment}/" + DIR_NAME
RUNS_DIR = f"{_ENV_ROOT}/runs"
CHAIN_STATE_DIR = f"{_ENV_ROOT}/chain_state"
LOCKS_DIR = f"{_ENV_ROOT}/locks"
STREAMS_DIR = f"{_ENV_ROOT}/streams"

# ── per project, relative to its root ─────────────────────────────────────────
SCHEMA_DIR = f"{DIR_NAME}/schema"
COMMENTS_DIR = f"{DIR_NAME}/comments"
CONFIG_LOCK = f"{DIR_NAME}/config.lock"
AUDIT_LOG = f"{DIR_NAME}/audit.log"

PathLike = Union[str, Path]


def local_env_dir(template: str, env: str) -> str:
    """``.ducta/<env>/<kind>``, relative to the project root, for an ``_ENV_ROOT`` template."""
    return f"{DIR_NAME}/{env}/{template.rsplit('/', 1)[-1]}"


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
