"""Unit tests for ducta.core.utils."""

from __future__ import annotations

import pytest

from ducta.core.utils import (
    compile_function,
    extract_dependency_name,
    extract_pipeline_nodes,
    get_node_dependencies,
    is_jit_enabled,
    jit,
    normalize_dependencies,
)


class TestNormalizeDependencies:
    def test_none(self):
        assert normalize_dependencies(None) == []

    def test_string(self):
        assert normalize_dependencies("a") == ["a"]

    def test_dict_keys(self):
        assert normalize_dependencies({"a": 1, "b": 2}) == ["a", "b"]

    def test_list_passthrough(self):
        assert normalize_dependencies(["a", "b"]) == ["a", "b"]

    def test_other_stringified(self):
        assert normalize_dependencies(42) == ["42"]


class TestExtractDependencyName:
    def test_string(self):
        assert extract_dependency_name("dep") == "dep"

    def test_single_key_dict(self):
        assert extract_dependency_name({"dep": {}}) == "dep"

    def test_multi_key_dict_raises(self):
        with pytest.raises(ValueError):
            extract_dependency_name({"a": 1, "b": 2})

    def test_none_raises(self):
        with pytest.raises(ValueError):
            extract_dependency_name(None)

    def test_bad_type_raises(self):
        with pytest.raises(TypeError):
            extract_dependency_name(3.14)


class TestExtractPipelineNodes:
    def test_string_nodes(self):
        assert extract_pipeline_nodes({"nodes": ["a", "b"]}) == ["a", "b"]

    def test_single_key_dict_node(self):
        assert extract_pipeline_nodes({"nodes": [{"a": {}}]}) == ["a"]

    def test_named_dict_node(self):
        assert extract_pipeline_nodes({"nodes": [{"name": "a", "x": 1}]}) == ["a"]

    def test_invalid_node_raises(self):
        with pytest.raises(ValueError):
            extract_pipeline_nodes({"nodes": [{"x": 1, "y": 2}]})


class TestGetNodeDependencies:
    def test_normalizes(self):
        assert get_node_dependencies({"dependencies": ["a", "b"]}) == ["a", "b"]

    def test_empty_default(self):
        assert get_node_dependencies({}) == []


class TestJit:
    def test_marks_function(self):
        @jit
        def f(x):
            return x

        assert is_jit_enabled(f) is True

    def test_with_options(self):
        @jit(nopython=True)
        def f(x):
            return x

        assert is_jit_enabled(f) is True

    def test_plain_function_not_jit(self):
        def f(x):
            return x

        assert is_jit_enabled(f) is False

    def test_compile_returns_original_when_not_jit(self):
        def f(x):
            return x * 2

        compiled = compile_function(f)
        assert compiled is f

    def test_cache_hit_returns_same_compiled_object_for_same_function(self):
        @jit
        def f(x):
            return x * 2

        first = compile_function(f)
        second = compile_function(f)
        assert second is first

    def test_distinct_functions_do_not_share_a_cache_entry(self):
        # The cache is keyed on the function object itself (a WeakKeyDictionary),
        # so two functions can never collide. It used to be keyed on id(func),
        # which meant a garbage-collected function's id could be reused by an
        # unrelated object and hand back the wrong compiled code — a hazard the
        # old implementation had to carry an extra strong reference to guard
        # against, at the cost of never releasing anything it had ever seen.
        @jit
        def f(x):
            return x * 2

        @jit
        def g(x):
            return x + 1

        compiled_f = compile_function(f)
        compiled_g = compile_function(g)

        assert compile_function(f) is compiled_f
        assert compile_function(g) is compiled_g

    def test_cache_does_not_retain_collected_functions(self):
        # The point of the weak keying: a function that goes out of scope must
        # not be pinned in memory (with its module and closure) for the life of
        # the process just because it was compiled once.
        import gc

        import ducta.core.utils as utils_module

        def _cache_size():
            return len(utils_module._jit_compile_cache) + len(utils_module._jit_fallback)

        def _make():
            @jit
            def transient(x):
                return x * 3

            compile_function(transient)
            return _cache_size()

        baseline = _cache_size()
        size_with_entry = _make()
        gc.collect()

        assert size_with_entry == baseline + 1
        assert _cache_size() == baseline
