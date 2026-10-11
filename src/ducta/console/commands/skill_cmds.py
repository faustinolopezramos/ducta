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

``ducta skill``: put Ducta's agent skill where an AI assistant finds it.

The skill (``ducta/skills/ducta``) follows the open Agent Skills format
(agentskills.io): a folder with ``SKILL.md``, read by Claude Code, Codex,
Gemini CLI, GitHub Copilot and other assistants. Each looks in its own folder;
``.agents/skills`` is the one most of them share.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger  # type: ignore

from ducta.console.core import ExitCode

SKILL_NAME = "ducta"


@dataclass(frozen=True)
class Target:
    label: str
    #: Relative to the project root.
    project: str
    #: Relative to the home directory.
    user: str


#: Where each assistant looks for skills (checked against their docs, 2026-10).
TARGETS: Dict[str, Target] = {
    # Codex reads only these; Gemini CLI and GitHub Copilot read them too.
    "agents": Target(
        "Codex, Gemini CLI, GitHub Copilot and others", ".agents/skills", ".agents/skills"
    ),
    "claude": Target("Claude Code", ".claude/skills", ".claude/skills"),
    "codex": Target("Codex", ".agents/skills", ".agents/skills"),
    "gemini": Target("Gemini CLI", ".gemini/skills", ".gemini/skills"),
    "copilot": Target("GitHub Copilot", ".github/skills", ".copilot/skills"),
}
#: Without --target: the shared folder, and Claude Code's own.
DEFAULT_TARGETS = ("agents", "claude")

_START = "<!-- ducta-skill:start -->"
_END = "<!-- ducta-skill:end -->"


def skill_source() -> Path:
    """The skill as shipped inside the package."""
    import ducta.skills

    return Path(ducta.skills.__file__).resolve().parent / SKILL_NAME


def skill_version(folder: Path) -> Optional[str]:
    """``metadata.skill-version`` of the skill in *folder*, if it is Ducta's."""
    try:
        text = (folder / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return None
    if not re.search(rf"^name:\s*{SKILL_NAME}\s*$", text, re.MULTILINE):
        return None
    m = re.search(r"^\s*skill-version:\s*[\"']?([\w.-]+)", text, re.MULTILINE)
    return m.group(1) if m else "unknown"


def _ignore(_folder: str, names: List[str]) -> List[str]:
    return [n for n in names if n == "__pycache__" or n.endswith((".pyc", ".pyo"))]


def install_to(parent: Path, force: bool = False) -> Tuple[Path, str]:
    """Copy the skill to ``parent/ducta``; what happened, in words."""
    source = skill_source()
    wanted = skill_version(source)
    if parent.exists() and not parent.is_dir():
        raise FileExistsError(f"{parent} is a file, not a folder: choose another --path")
    dest = parent / SKILL_NAME
    if dest.exists():
        there = skill_version(dest)
        if there is None:
            raise FileExistsError(f"{dest} exists and is not Ducta's skill; it was left alone")
        if there == wanted and not force:
            return dest, f"already installed (version {there})"
        if not force:
            raise FileExistsError(
                f"{dest} holds version {there} of the skill; this Ducta ships {wanted}. "
                "Pass --force to replace it"
            )
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest, ignore=_ignore)
    return dest, f"installed (version {wanted})"


def agents_md_block(skill_path: str) -> str:
    return "\n".join(
        [
            _START,
            "## Ducta",
            "",
            "This project is a [Ducta](https://github.com/faustinolopezramos/ducta) data-pipeline "
            "project (`ducta.yaml`). Before configuring, running or debugging it, read the Ducta "
            f"skill at `{skill_path}/SKILL.md` and follow it.",
            "",
            "- State of the project: `ducta config validate --env dev --output-format json`",
            "- Format of every file: `ducta config schema`",
            "- Never commit, run in `prod`, or write credentials to files unless asked.",
            _END,
        ]
    )


def write_agents_md(root: Path, skill_path: str) -> Path:
    """Add, or bring up to date, Ducta's block in ``root/AGENTS.md``; the rest is kept."""
    path = root / "AGENTS.md"
    block = agents_md_block(skill_path)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    pattern = re.compile(re.escape(_START) + r".*?" + re.escape(_END), re.DOTALL)
    if pattern.search(text):
        text = pattern.sub(lambda _m: block, text)
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + block
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def export_zip(destination: Path) -> Path:
    """The skill as a zip whose root is the ``ducta/`` folder (claude.ai, the Skills API)."""
    source = skill_source()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source.rglob("*")):
            if path.is_dir() or _ignore("", [path.name]) or "__pycache__" in path.parts:
                continue
            zf.write(path, Path(SKILL_NAME) / path.relative_to(source))
    return destination


def _project_root(start: Optional[Path] = None) -> Optional[Path]:
    """The project at or above *start* (the current directory): where its ``ducta.yaml`` is."""
    from ducta.setting.project_loader import find_project_root

    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        root = find_project_root(folder)
        if root is not None:
            return root
    return None


class SkillCommands:
    """Entry point for ``ducta skill``."""

    @staticmethod
    def handle(parsed_args) -> int:
        command = getattr(parsed_args, "skill_command", None)
        try:
            if command == "install":
                return SkillCommands.install(parsed_args)
            if command == "export":
                return SkillCommands.export(parsed_args)
            if command == "path":
                print(skill_source())
                return ExitCode.SUCCESS.value
        except (OSError, FileExistsError) as e:
            logger.error("{}", e)
            return ExitCode.GENERAL_ERROR.value
        logger.error("Unknown skill command: {}", command)
        return ExitCode.GENERAL_ERROR.value

    @staticmethod
    def install(parsed_args) -> int:
        found = _project_root()
        root = found or Path.cwd()
        in_project = not parsed_args.user and not getattr(parsed_args, "path", None)
        if in_project and found is None:
            logger.warning(
                "No ducta.yaml here or in a parent folder: installing in {}. Run it inside a "
                "project, or pass --global to install it for every project.",
                root,
            )
        if getattr(parsed_args, "path", None):
            parents = [("--path", Path(parsed_args.path).expanduser())]
        else:
            names = parsed_args.target or list(DEFAULT_TARGETS)
            base = Path.home() if parsed_args.user else root
            seen: Dict[Path, str] = {}
            for name in names:
                target = TARGETS[name]
                folder = base / (target.user if parsed_args.user else target.project)
                seen.setdefault(folder, name)
            parents = [(name, folder) for folder, name in seen.items()]

        failed = False
        installed: List[Path] = []
        for name, parent in parents:
            try:
                dest, what = install_to(parent, force=parsed_args.force)
            except FileExistsError as e:
                logger.error("{}", e)
                failed = True
                continue
            installed.append(dest)
            label = TARGETS[name].label if name in TARGETS else "your assistant"
            print(f"✓ {dest} — {what} — for {label}")

        if parsed_args.agents_md and installed:
            # The shared folder when it was installed there: most assistants read it.
            shared = [d for d in installed if d.parent.as_posix().endswith(".agents/skills")]
            first = (shared or installed)[0]
            try:
                shown = first.relative_to(root).as_posix()
            except ValueError:
                shown = str(first)
            print(f"✓ {write_agents_md(root, shown)} — points assistants to the skill")
        if installed:
            print("  Restart your assistant (skills are read when it starts), then ask it, e.g.")
            print('  "validate my Ducta project and fix the errors".')
        if installed and in_project and found is not None:
            print("  Commit these folders to share the skill with your team.")
        return ExitCode.GENERAL_ERROR.value if failed else ExitCode.SUCCESS.value

    @staticmethod
    def export(parsed_args) -> int:
        out = export_zip(Path(parsed_args.zip).expanduser())
        print(
            f"✓ {out} — upload it to claude.ai, the Skills API, or any assistant that takes a zipped skill"
        )
        return ExitCode.SUCCESS.value


def handle_skill(parsed_args) -> int:
    return SkillCommands.handle(parsed_args)
