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

import functools
from typing import Callable
from weakref import WeakKeyDictionary, WeakSet

from loguru import logger  # type: ignore

from ducta.setting.dependency_inference import (
    extract_dependency_name,
    extract_pipeline_nodes,
    get_node_dependencies,
    normalize_dependencies,
)

# These four live in `ducta.setting.dependency_inference` but are re-exported
# here, because callers already import them from `ducta.core.utils`. Listing
# them in `__all__` is what marks them as a deliberate public surface: the
# trailing `# noqa: F401` this replaces sat on the closing parenthesis, which
# ruff does not attach to the individual names, so F401 fired anyway — and
# `ruff check --fix` would have happily deleted imports that 11 call sites
# depend on.
__all__ = [
    "extract_dependency_name",
    "extract_pipeline_nodes",
    "get_node_dependencies",
    "normalize_dependencies",
    "jit",
]


def jit(func: Callable = None, **kwargs):
    """
    Decorator to enable JIT compilation for Ducta transformation functions.
    Uses Numba to compile Python code to machine code for extreme performance.
    """

    def decorator(f):
        f._Ducta_jit = True
        f._Ducta_jit_options = kwargs

        @functools.wraps(f)
        def wrapper(*args, **inner_kwargs):
            return f(*args, **inner_kwargs)

        return wrapper

    if func is None:
        return decorator
    return decorator(func)


def is_jit_enabled(func: Callable) -> bool:
    """Check if a function is marked for JIT compilation."""
    actual_func = getattr(func, "__wrapped__", func)
    return getattr(actual_func, "_Ducta_jit", False)


_jit_compile_cache: "WeakKeyDictionary[Callable, Callable]" = WeakKeyDictionary()
_jit_fallback: "WeakSet[Callable]" = WeakSet()


def compile_function(func: Callable) -> Callable:
    """
    Compile a function using Numba if marked for JIT.
    Returns the compiled function or the original if JIT is not enabled.
    """
    if not is_jit_enabled(func):
        return func

    try:
        if func in _jit_fallback:
            return func
    except TypeError:  # pragma: no cover - not weak-referenceable
        pass

    cached = _jit_compile_cache.get(func)
    if cached is not None:
        return cached

    try:
        import numba

        actual_func = getattr(func, "__wrapped__", func)
        options = getattr(actual_func, "_Ducta_jit_options", {})

        numba_options = {"nopython": True, "cache": True, **options}

        logger.info(
            f"JIT compiling function '{func.__name__}' with Numba (options={numba_options})"
        )
        compiled = numba.jit(actual_func, **numba_options)
    except ImportError:
        logger.warning(f"Numba not installed. Skipping JIT compilation for '{func.__name__}'.")
        compiled = func
    except Exception as e:
        logger.error(
            f"Failed to JIT compile '{func.__name__}': {e}. Falling back to standard execution."
        )
        compiled = func

    try:
        if compiled is func:
            _jit_fallback.add(func)
        else:
            _jit_compile_cache[func] = compiled
    except TypeError:  # pragma: no cover - not weak-referenceable
        pass
    return compiled
