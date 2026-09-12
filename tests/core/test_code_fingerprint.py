"""Tests for hashing the logic a run executed (``ducta.core.code_fingerprint``)."""

from __future__ import annotations

import textwrap

import pytest

from ducta.core.code_fingerprint import (
    ALGO_SOURCE,
    SCOPE_FUNCTION,
    SCOPE_MODULE,
    SCOPE_NONE,
    clear_cache,
    fingerprint_callable,
    fingerprint_module,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_cache()
    yield
    clear_cache()


def _sample(a, b):
    return a + b


def _sample_same_body(a, b):
    return a + b


class TestFingerprintCallable:
    def test_hashes_source_and_module(self):
        fp = fingerprint_callable(_sample)

        assert fp["algorithm"] == ALGO_SOURCE
        assert fp["scope"] == SCOPE_FUNCTION
        assert fp["source_hash"].startswith("sha256:")
        assert fp["module_hash"].startswith("sha256:")
        assert fp["degraded_reason"] is None
        assert fp["module_file"].endswith("test_code_fingerprint.py")

    def test_is_stable_across_calls(self):
        assert fingerprint_callable(_sample) == fingerprint_callable(_sample)

    def test_declared_names_override_introspection(self):
        fp = fingerprint_callable(_sample, module="nodes", function="clean_sales")

        assert fp["module"] == "nodes"
        assert fp["function"] == "clean_sales"

    def test_identical_bodies_hash_alike_but_names_do_not_hide_a_change(self):
        # Same text, different name: the source *includes* the def line, so the
        # hashes differ. This is the property that makes a swapped
        # implementation visible.
        assert (
            fingerprint_callable(_sample)["source_hash"]
            != fingerprint_callable(_sample_same_body)["source_hash"]
        )

    def test_a_changed_body_changes_the_hash(self, tmp_path, monkeypatch):
        module_dir = tmp_path
        monkeypatch.syspath_prepend(str(module_dir))

        src = module_dir / "swappable_node.py"
        src.write_text("def transform(df):\n    return df.dropna()\n")

        import importlib

        mod = importlib.import_module("swappable_node")
        before = fingerprint_callable(mod.transform)

        src.write_text("def transform(df):\n    return df  # quietly stopped cleaning\n")
        clear_cache()
        mod = importlib.reload(mod)
        after = fingerprint_callable(mod.transform)

        assert before["source_hash"] != after["source_hash"]
        assert before["module_hash"] != after["module_hash"]

    def test_a_changed_helper_moves_the_module_hash_only(self, tmp_path, monkeypatch):
        """The reason both hashes exist: `source_hash` alone misses helpers."""
        monkeypatch.syspath_prepend(str(tmp_path))
        src = tmp_path / "helper_node.py"
        src.write_text(
            textwrap.dedent(
                """
                def _rule(row):
                    return row > 0

                def transform(rows):
                    return [r for r in rows if _rule(r)]
                """
            )
        )

        import importlib

        mod = importlib.import_module("helper_node")
        before = fingerprint_callable(mod.transform)

        src.write_text(
            textwrap.dedent(
                """
                def _rule(row):
                    return True  # the actual logic change

                def transform(rows):
                    return [r for r in rows if _rule(r)]
                """
            )
        )
        clear_cache()
        mod = importlib.reload(mod)
        after = fingerprint_callable(mod.transform)

        assert before["source_hash"] == after["source_hash"], "transform's own text is unchanged"
        assert before["module_hash"] != after["module_hash"], "the helper edit must be visible"

    def test_unwraps_decorators(self):
        import functools

        def decorate(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)

            return wrapper

        decorated = decorate(_sample)
        clear_cache()
        assert (
            fingerprint_callable(decorated)["source_hash"]
            == (fingerprint_callable(_sample)["source_hash"])
        )

    def test_unwraps_a_jit_style_dispatcher(self):
        class FakeDispatcher:
            """Shaped like a Numba dispatcher: keeps the original as `py_func`."""

            def __init__(self, py_func):
                self.py_func = py_func

        clear_cache()
        expected = fingerprint_callable(_sample)["source_hash"]
        clear_cache()
        assert fingerprint_callable(FakeDispatcher(_sample))["source_hash"] == expected

    def test_degrades_with_a_reason_instead_of_raising(self):
        fp = fingerprint_callable(len)  # a builtin has no Python source

        assert fp["source_hash"] is None
        assert fp["scope"] in (SCOPE_MODULE, SCOPE_NONE)
        assert fp["degraded_reason"]

    def test_never_raises_on_a_runtime_built_callable(self):
        built = eval("lambda x: x * 2")  # noqa: S307 — deliberately sourceless

        fp = fingerprint_callable(built)

        assert fp["degraded_reason"]
        assert fp["source_hash"] is None


class TestFingerprintModule:
    def test_hashes_an_imported_module_file(self):
        fp = fingerprint_module("ducta.core.code_fingerprint")

        assert fp["scope"] == SCOPE_MODULE
        assert fp["module_hash"].startswith("sha256:")
        assert fp["function"] is None

    def test_reports_a_module_that_was_never_imported(self):
        fp = fingerprint_module("some.extension.nobody.imported")

        assert fp["module_hash"] is None
        assert fp["scope"] == SCOPE_NONE
        assert "not imported" in fp["degraded_reason"]
