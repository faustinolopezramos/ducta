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

Hashing the *logic* a run executed, so the certificate attests execution and
not only data.

``config_fingerprint`` covers the five config documents, which name a node's
transformation as ``module: "nodes", function: "clean_sales"`` — a pointer.
Nothing hashed the thing pointed at, so two runs whose certificates matched
field for field could have executed completely different code, and
``certify verify`` had no way to tell. ``git_commit``/``git_dirty`` in the
environment snapshot are the closest prior signal and they are not enough:
they need a git repo, ``dirty: true`` never says *what* changed, and code
imported from site-packages is outside the working tree entirely.

Two hashes are recorded per node, because they fail differently:

``source_hash``
    ``inspect.getsource`` of the callable itself. Precise — it changes when and
    only when that function's text changes — but blind to helpers the function
    calls.

``module_hash``
    The bytes of the file the callable was defined in. Coarse — an unrelated
    edit elsewhere in the file moves it — but it *does* cover the helpers
    defined alongside, which is where the logic that ``source_hash`` misses
    usually lives.

Neither reaches a helper imported from a third module. That is a real limit,
recorded rather than papered over: ``scope`` says exactly how far the hash
reaches, so a reader of the certificate knows what the hash did and did not
commit to. Extending coverage to the full import closure is a later, much more
expensive step, and it would still want these two as its base case.

Every function here is best-effort in the same sense as the rest of the
evidence path: a fingerprint that cannot be computed comes back with a
``degraded_reason`` naming why, never as a silent absence and never as an
exception that breaks a run.

Not the only code hash in the codebase, and deliberately so.
``PipelineExecutor._code_fingerprint`` hashes the same module *bytes* for the
chain-reuse check, but it answers a different question under different
constraints: one digest for a whole pipeline, computed *before* execution and
without importing anything, so a stale ancestor is not skipped as "up to date".
This module runs after the callable is in hand, which is what buys per-node
attribution and function-level precision — neither of which that path can have,
and neither of which it needs. Both hash raw file bytes, so the two agree about
what "the module changed" means.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from loguru import logger  # type: ignore

#: Bumped when the *meaning* of a hash changes, so certificates written by
#: different Ducta versions compare as "not comparable" instead of as a code
#: change that never happened. Mirrors the convention in
#: ``ducta.mlrun.fingerprint``.
ALGO_SOURCE = "source-sha256/v1"

_HASH_PREFIX = "sha256:"

#: How far a ``source_hash`` reaches. ``function`` is the callable's own text;
#: ``module`` means only the file hash could be computed (a C extension, a
#: callable built at runtime), so there is no per-function text to commit to.
SCOPE_FUNCTION = "function"
SCOPE_MODULE = "module"
SCOPE_NONE = "none"

#: Keyed by ``(module, qualname)``. Source does not change within a process,
#: and ``FunctionLoader`` re-records on every load — including cache hits, so a
#: chained pipeline's second certificate is not missing its code evidence — so
#: without this the same file would be read once per node per pipeline.
#:
#: Deliberately *not* keyed by ``id(target)``: CPython reuses the id of a
#: collected object, so a key carrying one can hand back another callable's
#: fingerprint — the single worst failure this module could have. A module
#: reloaded in-process with new source is the cost of that choice; it is why
#: :func:`clear_cache` exists.
_CACHE: Dict[tuple, Dict[str, Any]] = {}


def _sha256_text(text: str) -> str:
    return _HASH_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return _HASH_PREFIX + hashlib.sha256(data).hexdigest()


def _unwrap(func: Any) -> Any:
    """Peel decorators and JIT wrappers off *func* to reach the defined Python.

    ``FunctionLoader`` runs every node function through ``compile_function``,
    which hands back a Numba dispatcher when the node opted into JIT. Hashing
    the dispatcher would hash Numba, not the user's transformation, so the
    ``py_func`` it keeps is what gets hashed — the same text the non-JIT path
    would produce, which also keeps a node's fingerprint stable across turning
    JIT on and off.
    """
    seen = set()
    current = func
    while True:
        marker = id(current)
        if marker in seen:  # pragma: no cover — defensive against a wrapper cycle
            return current
        seen.add(marker)

        # Numba dispatchers keep the original under `py_func`.
        py_func = getattr(current, "py_func", None)
        if py_func is not None and callable(py_func):
            current = py_func
            continue

        wrapped = getattr(current, "__wrapped__", None)
        if wrapped is not None and callable(wrapped):
            current = wrapped
            continue

        return current


def _module_file_hash(
    target: Any,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """``(module_hash, module_file, reason)`` for the file *target* is defined in."""
    try:
        path = inspect.getfile(target)
    except (TypeError, OSError) as e:
        return None, None, f"module file not resolvable: {e}"

    try:
        data = Path(path).read_bytes()
    except OSError as e:
        return None, path, f"module file unreadable: {e}"

    return _sha256_bytes(data), path, None


def fingerprint_callable(
    func: Callable,
    *,
    module: Optional[str] = None,
    function: Optional[str] = None,
) -> Dict[str, Any]:
    """Hash the source of *func*, and of the file it was defined in.

    Never raises. When the source cannot be read — a builtin, a C extension, a
    callable assembled at runtime, a module whose file is gone — the returned
    dict carries ``degraded_reason`` and whichever of the two hashes was still
    obtainable, so the certificate records *that a gap exists and why* rather
    than omitting the node.
    """
    target = _unwrap(func)

    declared_module = module or getattr(target, "__module__", None) or "?"
    declared_function = function or getattr(target, "__qualname__", None) or "?"

    cache_key = (declared_module, declared_function)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    record: Dict[str, Any] = {
        "module": declared_module,
        "function": declared_function,
        "algorithm": ALGO_SOURCE,
        "scope": SCOPE_NONE,
        "source_hash": None,
        "module_hash": None,
        "module_file": None,
        "degraded_reason": None,
    }

    module_hash, module_file, module_reason = _module_file_hash(target)
    record["module_hash"] = module_hash
    record["module_file"] = module_file

    try:
        source = inspect.getsource(target)
    except (OSError, TypeError) as e:
        # OSError: no source available (builtin, C extension, REPL-defined).
        # TypeError: not a module/class/function/traceback/frame/code object.
        record["degraded_reason"] = f"source unavailable: {e}"
        record["scope"] = SCOPE_MODULE if module_hash else SCOPE_NONE
        if module_reason and not module_hash:
            record["degraded_reason"] = f"{record['degraded_reason']}; {module_reason}"
        logger.debug(
            "No source for '{}.{}': {} — certificate records a degraded code fingerprint",
            declared_module,
            declared_function,
            e,
        )
    else:
        record["source_hash"] = _sha256_text(source)
        record["scope"] = SCOPE_FUNCTION
        if module_reason:
            record["degraded_reason"] = module_reason

    _CACHE[cache_key] = dict(record)
    return record


def fingerprint_module(module_path: str) -> Dict[str, Any]:
    """Hash an importable module by file, for code named in config rather than called.

    Used for ``quality.extensions``: modules Ducta imports so their
    ``@register_check`` decorators run. Their verdicts land in the certificate's
    ``quality`` block, so a check quietly rewritten to always pass would produce
    an identically healthy-looking certificate. Hashing the file closes that.

    Imports nothing: the module is already imported by the time a certificate is
    built (``load_quality_extensions`` runs during context construction), and
    importing here to compute evidence would be a side effect in the wrong place.
    """
    record: Dict[str, Any] = {
        "module": module_path,
        "function": None,
        "algorithm": ALGO_SOURCE,
        "scope": SCOPE_MODULE,
        "source_hash": None,
        "module_hash": None,
        "module_file": None,
        "degraded_reason": None,
    }

    import sys

    mod = sys.modules.get(module_path)
    if mod is None:
        record["scope"] = SCOPE_NONE
        record["degraded_reason"] = "module not imported at certificate time"
        return record

    module_hash, module_file, reason = _module_file_hash(mod)
    record["module_hash"] = module_hash
    record["module_file"] = module_file
    if reason:
        record["scope"] = SCOPE_NONE
        record["degraded_reason"] = reason
    return record


def clear_cache() -> None:
    """Drop memoized fingerprints. For tests that rewrite a module on disk."""
    _CACHE.clear()
