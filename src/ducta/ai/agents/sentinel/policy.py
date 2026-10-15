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

Whether Sentinel may act — the one gate every action goes through.

It may only when the project turned it on (``sentinel.enabled``), the
environment is one it lists and is **not protected** (checked here again,
whatever the file says), the pipeline matches, nobody paused it, and the
day's budget is not spent.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ducta.ai.agents import audit
from ducta.ai.agents.store import agent_dir

AGENT = "sentinel"


@dataclass
class Settings:
    """The project's ``sentinel:`` block and protected environments, read once."""

    policy: Any
    protected: List[str]

    @classmethod
    def of(cls, root: Path) -> Optional["Settings"]:
        """The project's settings, or ``None`` when it does not load."""
        from ducta.setting.project_loader import ProjectConfigError, validate_project

        try:
            project = validate_project(root).project
        except ProjectConfigError:
            return None
        return cls(project.sentinel, list(project.governance.protected_environments))


def paused_path(root: Path) -> Path:
    return agent_dir(root, AGENT) / "PAUSED"


def is_paused(root: Path) -> bool:
    return paused_path(root).exists()


def pause(root: Path, by: str = "", reason: str = "") -> None:
    path = paused_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{by}\n{reason}\n", encoding="utf-8")
    audit.record(root, AGENT, "pause", target={}, result="paused", reason=reason, actor=by or None)


def resume(root: Path, by: str = "") -> None:
    paused_path(root).unlink(missing_ok=True)
    audit.record(root, AGENT, "resume", target={}, result="resumed", actor=by or None)


def actions_today(root: Path) -> int:
    return audit.count_since(root, AGENT, 24, action="rerun", result="started")


def may_act(root: Path, settings: Settings, env: str, pipeline: str) -> Tuple[bool, str]:
    """``(True, "")`` when Sentinel may re-run *pipeline* in *env*; else ``(False, why)``."""
    policy = settings.policy
    if not policy.enabled:
        return False, "sentinel.enabled is false"
    if env in settings.protected:
        return False, f"{env} is a protected environment: Sentinel only observes and proposes there"
    if env not in policy.environments:
        return False, f"{env} is not in sentinel.environments ({', '.join(policy.environments)})"
    if not any(fnmatch.fnmatchcase(pipeline, g) for g in policy.pipelines):
        return False, f"{pipeline} is not in sentinel.pipelines"
    if is_paused(root):
        return False, "Sentinel is paused (`ducta ai sentinel resume`)"
    done = actions_today(root)
    if done >= policy.max_actions_per_day:
        return False, f"the day's budget is spent ({done} of {policy.max_actions_per_day} re-runs)"
    return True, ""


def backoff(policy: Any, attempt: int) -> int:
    """Seconds to wait before re-run number *attempt* (0-based); the last value repeats."""
    steps = list(policy.retry_infra.backoff_seconds) or [0]
    return int(steps[min(attempt, len(steps) - 1)])
