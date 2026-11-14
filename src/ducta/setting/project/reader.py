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

Find a format-2 project and read its files, remembering where each key came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml  # type: ignore[import-untyped]

from ducta.setting.exceptions import ConfigurationError
from ducta.setting.project import files as pf
from ducta.setting.project.defaults import (
    apply_defaults,
    resolve_extends,
    resolve_node_templates,
    resolve_pipeline_uses,
)
from ducta.setting.project.schema import (
    PROJECT_FORMAT_VERSION,
)

PROJECT_FILE = "ducta.yaml"


CATALOG_FILE = "catalog.yaml"


CATALOG_DIR = "catalog"


QUALITY_DIR = "quality"


PROFILES_STEM = "profiles"


PIPELINES_DIR = "pipelines"


class ProjectConfigError(ConfigurationError):
    """One or more problems in a format-2 project, each located as file:line."""

    def __init__(self, problems: List[str]) -> None:
        self.problems = problems
        bullet = "\n  - "
        super().__init__(
            f"Invalid project configuration ({len(problems)} problem(s)):{bullet}"
            + bullet.join(problems)
        )


# ── detection ────────────────────────────────────────────────────────────────


def find_project_root(start: Path) -> Optional[Path]:
    """The directory holding a ``ducta.yaml`` / ``.toml`` / ``.json`` with ``version: 2``
    (``start`` or its ``config/``)."""
    for candidate in (start, start / "config"):
        if any(_declares_v2(f) for f in pf.find_files(candidate, "ducta")):
            return candidate
    return None


def project_file(root: Path) -> Path:
    """The project's ``ducta.*`` file (``ducta.yaml`` when there is none yet)."""
    found = pf.find_files(Path(root), "ducta")
    return found[0] if found else Path(root) / PROJECT_FILE


def _declared_version(path: Path) -> Any:
    """The ``version`` a ``ducta.*`` file declares; None when it has none or does not parse."""
    return _read_version(path)[0]


def _read_version(path: Path) -> "tuple[Any, Optional[str]]":
    """``(version, problem)`` of a ``ducta.*`` file: *problem* says why it cannot be read."""
    try:
        data = pf.load(path)
    except Exception as e:  # noqa: BLE001 — reported by other_format, not raised here
        return None, str(e)
    return (data.get("version") if isinstance(data, dict) else None), None


def _declares_v2(path: Path) -> bool:
    return bool(_declared_version(path) == PROJECT_FORMAT_VERSION)


def other_format(start: Path) -> Optional[str]:
    """Why the nearest ``ducta.*`` at or above *start* is not a project this Ducta reads.

    A project written for another format (a newer Ducta's ``version: 3``) used to
    be reported as no project at all, and so was a ``ducta.*`` that does not parse
    (a YAML error, a key written twice): the message is then the parse error, with
    its line. None when the nearest one is format 2, or when no ``ducta.*`` exists
    or declares a version.
    """
    start = Path(start).resolve()
    for directory in (start, *start.parents):
        for candidate in (directory, directory / "config"):
            found = pf.find_files(candidate, "ducta")
            read = [(path, *_read_version(path)) for path in found]
            if any(v == PROJECT_FORMAT_VERSION for _, v, _problem in read):
                return None
            for path, declared, problem in read:
                if problem is not None:
                    # A project file that does not parse is the project: saying "no project
                    # here" sent people looking for a file that was in front of them.
                    return f"{path}: {problem}"
                if declared is not None:
                    return _other_format_message(path, declared)
    return None


def _other_format_message(path: Path, declared: Any) -> str:
    from ducta import __version__

    if isinstance(declared, int) and declared > PROJECT_FORMAT_VERSION:
        return (
            f"{path} uses project format {declared}; this Ducta ({__version__}) reads "
            f"format {PROJECT_FORMAT_VERSION}: upgrade Ducta (pip install -U ducta)"
        )
    return f"{path} declares `version: {declared}`; Ducta reads `version: {PROJECT_FORMAT_VERSION}`"


# ── reading, with positions ──────────────────────────────────────────────────


@dataclass
class _Located:
    """Parsed documents plus where each key path was written."""

    project: Dict[str, Any]
    catalog: Dict[str, Any]
    pipelines: Dict[str, Dict[str, Any]]
    #: ("catalog", "silver.orders", "path") → "catalog.yaml:12"
    where: Dict[Tuple[str, ...], str] = field(default_factory=dict)
    pipeline_files: Dict[str, Path] = field(default_factory=dict)
    #: dataset name → the catalog file that declares it
    catalog_files: Dict[str, Path] = field(default_factory=dict)
    #: ``quality/profiles.*`` and the profile names it declares
    profiles_file: Optional[Path] = None
    file_profiles: Tuple[str, ...] = ()


def visible_in(path: Path, base: Path) -> bool:
    """Not inside a hidden folder (``.claude/``, ``.ipynb_checkpoints/``…) under *base*."""
    return not any(part.startswith(".") for part in path.relative_to(base).parts[:-1])


def catalog_dir_files(root: Path) -> List[Path]:
    """The files of ``catalog/`` (any depth), in a stable order — ``[]`` when there is none."""
    base = Path(root) / CATALOG_DIR
    if not base.is_dir():
        return []
    return sorted(
        p
        for p in base.rglob("*")
        if p.is_file() and p.suffix.lower() in pf.SUFFIXES and visible_in(p, base)
    )


def catalog_location(root: Path) -> Path:
    """Where the catalog lives: the ``catalog/`` folder, or the single ``catalog.*`` file."""
    root = Path(root)
    if catalog_dir_files(root):
        return root / CATALOG_DIR
    found = pf.find_files(root, "catalog")
    return found[0] if found else root / CATALOG_FILE


def _read(
    path: Path, prefix: Tuple[str, ...], where: Dict[Tuple[str, ...], str], root: Path
) -> Any:
    text = path.read_text(encoding="utf-8")
    rel = str(path.relative_to(root))
    try:
        data = pf.parse(path, text)
        pf.index(path, text, prefix, where, rel)
    except ValueError as e:
        raise ProjectConfigError([f"{rel}: {e}"]) from e
    except yaml.YAMLError as e:
        raise ProjectConfigError([f"{rel}: not valid YAML — {e}"]) from e
    return data


def read_project(root: Path, *, expand: bool = True) -> _Located:
    """Read ``ducta.*``, the catalog (``catalog.*`` or every ``catalog/**/*.*``) and every
    ``pipelines/**/*.*`` (YAML, TOML or JSON).

    ``expand=False`` leaves ``extends`` and ``defaults`` unresolved, which is how
    ``ducta config explain`` tells a value written in a file from one it inherited.
    """
    root = Path(root)
    where: Dict[Tuple[str, ...], str] = {}
    problems: List[str] = []
    singles: Dict[str, Path] = {}
    for stem in ("ducta", "catalog"):
        found = pf.find_files(root, stem)
        if len(found) > 1:
            names = " and ".join(f.name for f in found)
            problems.append(f"{names}: a project keeps one {stem} file; remove all but one")
        if found:
            singles[stem] = found[0]
    dir_files = catalog_dir_files(root)
    if dir_files and "catalog" in singles:
        problems.append(
            f"{singles['catalog'].name} and {CATALOG_DIR}/: a project keeps its datasets in one "
            f"place; use {singles['catalog'].name} or {CATALOG_DIR}/, not both"
        )
    if problems:
        raise ProjectConfigError(problems)
    project = _read(singles.get("ducta", root / PROJECT_FILE), ("project",), where, root)
    profiles_path, file_profiles = _merge_profiles(root, project, where, problems)
    catalog: Dict[str, Any] = {}
    catalog_files: Dict[str, Path] = {}
    for path in dir_files or ([singles["catalog"]] if "catalog" in singles else []):
        data = _read(path, ("catalog",), where, root)
        if data is None:
            continue
        if not isinstance(data, dict):
            problems.append(
                f"{path.relative_to(root)}: a catalog file maps dataset names to datasets"
            )
            continue
        for name, entry in data.items():
            if name in catalog:
                problems.append(
                    f"{where.get(('catalog', str(name)), str(path.relative_to(root)))} dataset "
                    f"'{name}' is already defined in {catalog_files[name].relative_to(root)} — "
                    "a dataset is declared once"
                )
                continue
            catalog[name] = entry
            catalog_files[name] = path
    if problems:
        raise ProjectConfigError(problems)
    pipelines: Dict[str, Dict[str, Any]] = {}
    files: Dict[str, Path] = {}
    pipeline_dir = root / PIPELINES_DIR
    candidates = (
        sorted(
            p
            for p in pipeline_dir.rglob("*")
            if p.suffix.lower() in pf.SUFFIXES and visible_in(p, pipeline_dir)
        )
        if pipeline_dir.is_dir()
        else []
    )
    for path in candidates:
        if not path.is_file():
            continue
        name = path.stem
        if name in pipelines:
            problems.append(
                f"{path.relative_to(root)}: pipeline '{name}' is already defined in "
                f"{files[name].relative_to(root)} — pipeline names come from file names "
                "and must be unique"
            )
            continue
        pipelines[name] = _read(path, ("pipelines", name), where, root)
        files[name] = path
    if problems:
        raise ProjectConfigError(problems)
    if not expand:
        return _Located(
            project, catalog, pipelines, where, files, catalog_files, profiles_path, file_profiles
        )
    pipelines, problems = resolve_extends(
        root, pipelines, lambda path: _read(path, ("templates", path.stem), where, root)
    )
    if problems:
        raise ProjectConfigError(problems)
    pipelines, catalog, problems = resolve_pipeline_uses(
        root,
        pipelines,
        catalog,
        lambda path: _read(path, ("templates", "pipelines", path.stem), where, root),
        lambda path: where.get(path) or where.get(path[:-1]) or "?",
    )
    if problems:
        raise ProjectConfigError(problems)
    pipelines, problems = resolve_node_templates(
        root,
        pipelines,
        lambda path: _read(path, ("templates", "nodes", path.stem), where, root),
        lambda path: where.get(path) or where.get(path[:-1]) or "?",
    )
    if problems:
        raise ProjectConfigError(problems)
    catalog, pipelines = apply_defaults(project, catalog, pipelines)
    return _Located(
        project, catalog, pipelines, where, files, catalog_files, profiles_path, file_profiles
    )


def _merge_profiles(
    root: Path, project: Any, where: Dict[Tuple[str, ...], str], problems: List[str]
) -> Tuple[Optional[Path], Tuple[str, ...]]:
    """Fold ``quality/profiles.*`` into ``settings.quality.profiles`` (before environments).

    A profile defined both there and in ``ducta.yaml`` is an error: two homes for one
    name would make the winner depend on an order nobody wrote down.
    """
    found = pf.find_files(root / QUALITY_DIR, PROFILES_STEM)
    if len(found) > 1:
        names = " and ".join(f"{QUALITY_DIR}/{f.name}" for f in found)
        raise ProjectConfigError(
            [f"{names}: a project keeps one profiles file; remove all but one"]
        )
    if not found or not isinstance(project, dict):
        return None, ()
    path = found[0]
    prefix = ("project", "settings", "quality", "profiles")
    profiles = _read(path, prefix, where, root)
    rel = str(path.relative_to(root))
    if profiles is None:
        return path, ()
    if not isinstance(profiles, dict):
        raise ProjectConfigError([f"{rel}: maps profile names to their checks"])
    settings = project.get("settings")
    if settings is None:
        settings = project["settings"] = {}
    quality = settings.get("quality") if isinstance(settings, dict) else None
    if quality is None and isinstance(settings, dict):
        quality = settings["quality"] = {}
    if not isinstance(quality, dict):
        return path, tuple(profiles)  # settings.quality is malformed; validation reports it
    existing = quality.get("profiles") or {}
    if not isinstance(existing, dict):
        return path, tuple(profiles)
    for name in profiles:
        if name in existing:
            problems.append(
                f"{where.get(('project', 'settings', 'quality', 'profiles', str(name)), rel)} "
                f"profile '{name}' is also defined in settings.quality.profiles of "
                f"ducta.yaml — define it in one place"
            )
    if problems:
        raise ProjectConfigError(problems)
    quality["profiles"] = {**existing, **profiles}
    return path, tuple(profiles)


def _conventional_path(name: str) -> Optional[str]:
    parts = [p for p in name.replace("/", ".").split(".") if p]
    if len(parts) != 3:
        return None
    return "${output_path}/${environment}/" + "/".join(parts)
