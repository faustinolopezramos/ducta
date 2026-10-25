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

The project's say over Ducta AI: the ``ai:`` block of its ``ducta.*`` file.

Which model answers is a property of the machine (``~/.ducta/ai.toml``);
whether a project may be sent to one is the project's. Every model request a
feature makes for a project goes through :func:`require_allowed` first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ducta.ai.config import AIConfig
from ducta.ai.errors import AIPolicyError


def project_policy(root: Path) -> Any:
    """The project's ``ai:`` block (an ``AIPolicy``), read from its ``ducta.*`` file alone
    (``ducta.yaml``, ``ducta.toml`` or ``ducta.json``).

    Only that block is read, so a project that does not validate — the one a fix
    is for — still has its say. A block that cannot be read allows nothing.
    """
    from pydantic import ValidationError

    from ducta.setting.project import files as pf
    from ducta.setting.project.loader import project_file
    from ducta.setting.project.schema import AIPolicy

    path = project_file(Path(root))
    try:
        data = pf.load(path) if path.is_file() else {}
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise AIPolicyError(f"{path.name} cannot be read, so its ai: block is unknown ({e})") from e
    block = data.get("ai") if isinstance(data, dict) else None
    try:
        return AIPolicy.model_validate(block or {})
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", ()))
        raise AIPolicyError(
            f"{path.name}: ai.{where}: {first.get('msg')} — nothing is sent to a model "
            "until the ai: block is valid"
        ) from e


def require_allowed(root: Path, config: AIConfig) -> None:
    """Raise unless the project lets *config*'s model receive it."""
    from ducta.setting.project.loader import project_file

    policy = project_policy(root)
    name = project_file(Path(root)).name
    if not policy.enabled:
        raise AIPolicyError(f"This project turns Ducta AI off (ai.enabled: false in {name})")
    if not policy.remote and not config.is_local:
        raise AIPolicyError(
            f"This project allows only a local model (ai.remote: false in {name}), "
            f"and {config.label} at {config.endpoint} is remote. Use a local one "
            "(`ducta ai setup --provider ollama`)."
        )


__all__ = ["project_policy", "require_allowed"]
