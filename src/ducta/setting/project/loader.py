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

Load a format-2 project and compile it to the engine's five documents.

``ducta.yaml`` + ``catalog.yaml`` + ``pipelines/**/*.yaml``  →
``global_config``, ``pipelines_config``, ``nodes_config``, ``input_config``,
``output_config`` — the documents the engine, preflight and certificates read
(``config_fingerprint`` hashes them).

Steps, each in its own module: ``reader`` reads the files (remembering where each key
came from), ``overlay`` applies the environment's overrides, ``validation`` checks the
schema and the cross-file references, ``compiler`` compiles. This module builds the
:class:`Context` and re-exports the names the rest of Ducta imports from here.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional

from loguru import logger

from ducta.setting.exceptions import ConfigurationError
from ducta.setting.project.schema import (
    PROJECT_FORMAT_VERSION,
)

if TYPE_CHECKING:
    from ducta.setting.contexts import Context
from ducta.setting.project.compiler import _checks, compile_project
from ducta.setting.project.overlay import (
    apply_environment,
    environment_overrides,
    project_tree,
    resolve_path,
)
from ducta.setting.project.reader import (
    CATALOG_DIR,
    CATALOG_FILE,
    PIPELINES_DIR,
    PROFILES_STEM,
    PROJECT_FILE,
    QUALITY_DIR,
    ProjectConfigError,
    _conventional_path,
    catalog_dir_files,
    catalog_location,
    find_project_root,
    other_format,
    project_file,
    read_project,
    visible_in,
)
from ducta.setting.project.validation import Project, validate_project

__all__ = [
    "CATALOG_DIR",
    "CATALOG_FILE",
    "PIPELINES_DIR",
    "PROFILES_STEM",
    "PROJECT_FILE",
    "Project",
    "ProjectConfigError",
    "QUALITY_DIR",
    "_checks",
    "_conventional_path",
    "apply_environment",
    "catalog_dir_files",
    "catalog_location",
    "compile_project",
    "environment_overrides",
    "find_project_root",
    "load_context_quality_extensions",
    "load_project",
    "load_project_v2",
    "project_file",
    "project_tree",
    "read_project",
    "resolve_path",
    "validate_project",
    "visible_in",
]


def _engine_problems(root: Path, project: "Project", error: BaseException) -> Optional[List[str]]:
    """The engine's schema errors, each at the project file that produced the value.

    The engine validates the five compiled documents with its own schema. When that
    rejects something the project schema let through, the raw error names engine
    paths (``nodes_config.extract.input``) nobody wrote; this maps them back to
    ``file:line``. ``None`` when the error is not a schema error.
    """
    from pydantic import ValidationError as _ValidationError

    cause = error.__cause__ if isinstance(error.__cause__, _ValidationError) else error
    if not isinstance(cause, _ValidationError):
        return None
    located = read_project(root)
    owner = {n: p for p, pl in project.pipelines.items() for n in pl.nodes}
    out: List[str] = []
    for err in cause.errors():
        loc = [str(x) for x in err["loc"]]
        head, name = (loc + ["", ""])[:2]
        rest = ".".join(loc[2:])
        if head == "pipelines_config" and name in located.pipelines:
            at = located.where.get(("pipelines", name), f"pipelines/{name}")
            what = f"pipeline '{name}'"
        elif head == "nodes_config" and name in owner:
            at = located.where.get(
                ("pipelines", owner[name], "nodes", name), f"pipelines/{owner[name]}"
            )
            what = f"node '{name}'"
        elif head in ("input_config", "output_config") and name in located.catalog:
            at = located.where.get(("catalog", name), CATALOG_FILE)
            what = f"dataset '{name}'"
        else:
            at, what = PROJECT_FILE, ".".join(loc[:2]) or "configuration"
        field = f".{rest}" if rest else ""
        msg = err["msg"].removeprefix("Value error, ")
        if head == "pipelines_config" and rest == "nodes" and err["type"] == "missing":
            # The API creates a pipeline before its first node, so the project itself may
            # be empty of nodes; running or loading one for execution may not.
            out.append(f"{at} {what} has no nodes — add at least one under `nodes:`")
            continue
        out.append(f"{at} {what}{field}: {msg} (rejected by the engine's own schema)")
    return out or None


def load_project_v2(root: Path, env: Optional[str], allow_python_config: bool = True) -> "Context":
    """A :class:`Context` for the format-2 project at ``root``.

    ``allow_python_config`` gates importing ``quality.extensions`` modules
    (the API server passes False).
    """
    from ducta.setting.contexts import Context

    project = validate_project(root, env)
    docs = compile_project(project)
    try:
        context = Context(
            global_config=docs["global_config"],
            pipelines_config=docs["pipelines_config"],
            nodes_config=docs["nodes_config"],
            input_config=docs["input_config"],
            output_config=docs["output_config"],
            env=env,
        )
    except Exception as e:  # noqa: BLE001 — the engine's schema rejected what ours accepted
        problems = _engine_problems(root, project, e)
        if problems is None:
            raise
        raise ProjectConfigError(problems) from e
    # Where the configuration came from, plus the format marker.
    setattr(context, "_config_file_path", str(project_file(root).resolve()))
    setattr(context, "config_paths", {})
    setattr(context, "project_format", PROJECT_FORMAT_VERSION)
    # Kept so a worker process rebuilding this Context applies the same trust boundary.
    setattr(context, "allow_python_config", allow_python_config)
    load_context_quality_extensions(context, allow_python_config)
    logger.info(
        "Loaded project '{}' (format 2): {} pipeline(s), {} dataset(s)",
        project.project.project,
        len(project.pipelines),
        len(project.catalog),
    )
    return context


def load_project(
    path: Optional[Any] = None, env: Optional[str] = None, allow_python_config: bool = True
) -> "Context":
    """The :class:`Context` of the project containing ``path`` (default: the cwd).

    ``path`` is the project directory, any directory or file inside it; the
    project is the nearest ``ducta.yaml`` with ``version: 2`` at or above it,
    as the CLI finds it. ``env`` applies that environment's overrides (default:
    the base project). Relative ``paths`` resolve against the working
    directory, as in a CLI run started from the project root.
    """
    start = Path(path) if path is not None else Path.cwd()
    if start.is_file():
        start = start.parent
    start = start.resolve()
    for directory in (start, *start.parents):
        root = find_project_root(directory)
        if root is not None:
            return load_project_v2(root, env, allow_python_config)
    raise ConfigurationError(
        other_format(start)
        or f"No Ducta project found at or above {start} (looked for {PROJECT_FILE}, "
        "ducta.toml or ducta.json with `version: 2`). Create one with `ducta template`."
    )


def load_context_quality_extensions(ctx: Any, allow_python_config: bool) -> None:
    """Import the custom check modules named in ``quality.extensions``.

    Shared by every way a Context is built. It imports arbitrary Python
    modules named in config, so it must not run when ``allow_python_config``
    is False (the API server's setting).
    """
    extensions = (ctx.global_config.get("quality") or {}).get("extensions") or []
    if extensions and not allow_python_config:
        logger.warning(
            "Skipping {} quality extension(s): allow_python_config is False, "
            "which forbids importing arbitrary Python modules from config.",
            len(extensions),
        )
    elif extensions:
        try:
            from ducta.check.core import load_quality_extensions

            load_quality_extensions(extensions)
        except Exception as exc:
            # The gates were written against these checks: running without them
            # would publish data the user asked to have verified.
            raise ProjectConfigError(
                [
                    f"{PROJECT_FILE} quality.extensions: cannot load {extensions}: "
                    f"{type(exc).__name__}: {exc}"
                ]
            ) from exc
