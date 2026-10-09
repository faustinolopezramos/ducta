"""Stale nodes: function changed since the last successful run, or upstream of one that did."""

from __future__ import annotations

import hashlib
import inspect
import sys
from pathlib import Path

from ducta.api.repositories.v2_store import V2ProjectStore
from ducta.api.services.staleness import function_source_hash, node_freshness

SRC = """import functools


def plain(orders):
    return orders


@functools.lru_cache
def decorated(x):
    return x
"""


def test_the_hash_is_the_one_the_certificate_records(tmp_path, monkeypatch):
    # The certificate hashes inspect.getsource(func) at run time.
    (tmp_path / "hashmod.py").write_text(SRC)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("hashmod", None)
    import hashmod

    for name in ("plain", "decorated"):
        func = getattr(hashmod, name)
        expected = "sha256:" + hashlib.sha256(inspect.getsource(func).encode()).hexdigest()
        assert function_source_hash(SRC, name) == expected
    assert function_source_hash(SRC, "missing") is None


def _project(tmp_path: Path) -> V2ProjectStore:
    (tmp_path / "ducta.yaml").write_text("version: 2\nproject: p\npaths: {input: d, output: d}\n")
    (tmp_path / "catalog.yaml").write_text(
        "raw: {format: csv, path: d/r}\nmid: {format: parquet, path: d/m}\nout: {format: parquet, path: d/o}\n"
    )
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "etl.yaml").write_text(
        "nodes:\n"
        "  etl.a:\n    run: src.m:a\n    inputs: {raw: raw}\n    outputs: [mid]\n"
        "  etl.b:\n    run: src.m:b\n    inputs: {mid: mid}\n    outputs: [out]\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text(
        "def a(raw):\n    return raw\n\n\ndef b(mid):\n    return mid\n"
    )
    store = V2ProjectStore.detect(tmp_path)
    assert store is not None
    return store


def _cert(store: V2ProjectStore) -> dict:
    src = (store.root / "src" / "m.py").read_text()
    return {
        "run_id": "r1",
        "started_at": "2026-10-01T00:00:00+00:00",
        "status": "success",
        "nodes": [{"name": "etl.a"}, {"name": "etl.b"}],
        "code": {
            "nodes": {
                f"src.m.{f}": {"source_hash": function_source_hash(src, f)} for f in ("a", "b")
            }
        },
    }


def test_unchanged_is_fresh_and_no_run_is_never(tmp_path):
    store = _project(tmp_path)
    assert {k: v.state for k, v in node_freshness(store, {"etl": _cert(store)}).items()} == {
        "etl.a": "fresh",
        "etl.b": "fresh",
    }
    assert {v.state for v in node_freshness(store, {}).values()} == {"never"}


def test_a_changed_function_is_stale_and_so_is_what_reads_it(tmp_path):
    store = _project(tmp_path)
    cert = _cert(store)
    (tmp_path / "src" / "m.py").write_text(
        "def a(raw):\n    return raw.dropna()\n\n\ndef b(mid):\n    return mid\n"
    )
    result = node_freshness(store, {"etl": cert})
    assert result["etl.a"].state == "stale"
    assert "a() changed" in result["etl.a"].reasons[0]
    assert result["etl.b"].state == "stale"
    assert "from etl.a" in result["etl.b"].reasons[0]
