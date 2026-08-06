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
from typing import Any, Callable, Dict, List
from weakref import WeakKeyDictionary, WeakSet

from loguru import logger  # type: ignore


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


def normalize_dependencies(dependencies: Any) -> List[Any]:
    """Normalize dependencies to a consistent list format."""
    if dependencies is None:
        return []
    elif isinstance(dependencies, str):
        return [dependencies]
    elif isinstance(dependencies, dict):
        return list(dependencies.keys())
    elif isinstance(dependencies, list):
        return dependencies
    else:
        return [str(dependencies)]


def extract_dependency_name(dependency: Any) -> str:
    """Extract dependency name from various formats."""
    if isinstance(dependency, str):
        return dependency
    elif isinstance(dependency, dict):
        if len(dependency) != 1:
            raise ValueError(f"Dict dependency must have exactly one key-value pair: {dependency}")
        return next(iter(dependency.keys()))
    elif dependency is None:
        raise ValueError("Dependency cannot be None")
    else:
        raise TypeError(f"Unsupported dependency type: {type(dependency)} - {dependency}")


def extract_pipeline_nodes(pipeline: Dict[str, Any]) -> List[str]:
    """Extract node names from pipeline configuration."""
    pipeline_nodes_raw = pipeline.get("nodes", [])
    pipeline_nodes = []
    for node in pipeline_nodes_raw:
        if isinstance(node, str):
            pipeline_nodes.append(node)
        elif isinstance(node, dict):
            if len(node) == 1:
                pipeline_nodes.append(next(iter(node)))
            elif "name" in node:
                pipeline_nodes.append(node["name"])
            else:
                raise ValueError(f"Invalid node format in pipeline: {node}")
        else:
            pipeline_nodes.append(str(node))
    return pipeline_nodes


def get_node_dependencies(node_config: Dict[str, Any]) -> List[str]:
    """Extract and normalize node dependencies."""
    dependencies = normalize_dependencies(node_config.get("dependencies", []))
    normalized_deps = []
    for dep in dependencies:
        try:
            dep_name = extract_dependency_name(dep)
            normalized_deps.append(dep_name)
        except (TypeError, ValueError) as e:
            logger.error(f"Error processing dependency {dep}: {str(e)}")
            raise
    return normalized_deps
