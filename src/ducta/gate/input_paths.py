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

Resolving a dataset's ``filepath`` to something Spark can read in local mode: directories
and files as they are, glob patterns checked to match something, and a missing path looked
up under the shared read-fallback prefixes of a trial run.
"""

from pathlib import Path
from typing import Optional, Sequence

from loguru import logger  # type: ignore

from ducta.gate.exceptions import ConfigurationError


def has_glob_pattern(path: str) -> bool:
    """Check if path contains glob pattern characters."""
    return any(character in str(path) for character in ("*", "?", "["))


def resolve_local_path(
    path: str, fallback_roots: Sequence[str] = (), own_output_path: Optional[str] = None
) -> str:
    """The local path to hand to Spark for ``path``, or ``ConfigurationError`` if there is none.

    ``fallback_roots`` and ``own_output_path`` are the context's ``_read_fallback_paths`` and
    ``output_path``: an input that is missing under this run's output path may live under a
    shared prefix.
    """
    path_obj = Path(path)

    if path_obj.is_dir() or path_obj.is_file():
        return path_obj.as_posix()

    if has_glob_pattern(path):
        return _check_glob(path_obj, path)

    if not path_obj.exists():
        fallback = _from_fallback(path_obj, fallback_roots, own_output_path)
        if fallback is not None:
            return fallback
        raise ConfigurationError(f"File '{path}' does not exist in local mode")

    return path_obj.as_posix()


def _from_fallback(
    path_obj: Path, fallback_roots: Sequence[str], own_output_path: Optional[str]
) -> Optional[str]:
    """Resolve a missing local input from a shared read-fallback prefix, if configured."""
    if not fallback_roots or not own_output_path:
        return None

    try:
        relative = path_obj.resolve().relative_to(Path(own_output_path).resolve())
    except ValueError:
        return None

    for fallback_root in fallback_roots:
        candidate = Path(fallback_root) / relative
        if candidate.exists():
            logger.debug(
                "Input '{}' not found under trial output_path; resolved from "
                "shared prefix '{}' instead.",
                path_obj,
                fallback_root,
            )
            return candidate.as_posix()
    return None


def _check_glob(path_obj: Path, path: str) -> str:
    """The pattern, normalized, if it matches at least one file."""
    if not path_obj.parent.exists():
        raise ConfigurationError(f"Parent directory for glob pattern '{path}' does not exist")

    matches = list(path_obj.parent.glob(path_obj.name))
    if matches:
        logger.debug("Glob pattern '{}' matched {} files", path, len(matches))
        return path_obj.as_posix()  # Return original pattern normalized for Spark to handle

    raise ConfigurationError(f"Glob pattern '{path}' matched no files in local mode")
