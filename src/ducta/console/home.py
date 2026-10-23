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

``ducta`` with no command: where you are, and what to type next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ProjectSummary:
    root: Path
    name: str
    pipelines: List[str] = field(default_factory=list)
    environments: List[str] = field(default_factory=list)
    #: Why the project could not be read, when it could not.
    problem: Optional[str] = None


def project_summary(start: Optional[Path] = None) -> Optional[ProjectSummary]:
    """The project at or above *start*, read without Spark (milliseconds)."""
    from ducta.setting.project_context import find_nearest_project

    root = find_nearest_project(start or Path.cwd())
    if root is None:
        return None
    try:
        from ducta.setting.project_loader import validate_project

        project = validate_project(root)
        return ProjectSummary(
            root=root,
            name=str(getattr(project.project, "project", "") or root.name),
            pipelines=sorted(project.pipelines),
            environments=list(project.project.environments or {}),
        )
    except Exception as e:  # noqa: BLE001 — a broken project is still "here"
        first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        return ProjectSummary(root=root, name=root.name, problem=first)


def print_home() -> None:
    """In a project: its pipelines and the next commands. Elsewhere: how to start."""
    from rich.text import Text

    from ducta import __version__
    from ducta.console.ux import view

    out = view.console()
    summary = project_summary()
    head = Text()
    head.append(f"ducta {__version__}", style="bold cyan")
    if summary is None:
        head.append(" · no project here", style="dim")
        out.print(head, soft_wrap=True)
        out.print()
        _commands(
            [
                ("ducta init project --name my_project", "create a project with a sample pipeline"),
                ("ducta init project --name my_project --type ml", "… an ML project"),
                ("ducta --help", "every command"),
            ]
        )
        return

    head.append(f" · {summary.name}", style="bold")
    where = view.display_path(summary.root)
    if where != ".":
        head.append(f" · {where}", style="dim")
    out.print(head, soft_wrap=True)
    if summary.problem:
        out.print(Text(f"  ! the project does not load: {summary.problem}", style="yellow"))
        out.print()
        _commands([("ducta check", "see every problem, with file and line")])
        return
    envs = ["base", *summary.environments]
    details = Text("  ")
    details.append(f"{len(summary.pipelines)} pipeline(s): ", style="dim")
    details.append(", ".join(summary.pipelines) or "none yet")
    details.append("   environments: ", style="dim")
    details.append(", ".join(envs))
    out.print(details, soft_wrap=True)
    out.print()
    env = "dev" if "dev" in summary.environments else envs[-1]
    pipeline = summary.pipelines[0] if summary.pipelines else "<pipeline>"
    _commands(
        [
            (f"ducta start -e {env} -p {pipeline}", "run a pipeline"),
            (f"ducta check -e {env}", "check the project without running it"),
            ("ducta certify list", "the runs recorded here"),
            ("ducta ui", "open the web app"),
            ("ducta --help", "every command"),
        ]
    )


def _commands(rows: List[tuple]) -> None:
    from rich.text import Text

    from ducta.console.ux import view

    width = max(len(cmd) for cmd, _ in rows) + 3
    for cmd, what in rows:
        line = Text("  ")
        line.append(cmd.ljust(width), style="bold")
        line.append(what, style="dim")
        view.console().print(line, soft_wrap=True)


def pipeline_hints(base_path: Optional[str] = None) -> List[tuple]:
    """``[("pipelines", "etl, sales")]`` for an error that needs a pipeline name."""
    summary = project_summary(Path(base_path) if base_path else None)
    if summary is None or summary.problem or not summary.pipelines:
        return []
    env = "dev" if "dev" in summary.environments else "base"
    return [
        ("pipelines", ", ".join(summary.pipelines)),
        ("e.g.", f"ducta start -e {env} -p {summary.pipelines[0]}"),
    ]
