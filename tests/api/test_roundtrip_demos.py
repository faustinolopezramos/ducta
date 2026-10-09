"""Editing a pipeline from the UI and undoing it leaves the file exactly as written —
on the real demo projects, whose files mix indentation styles, comments and blank lines."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("ruamel.yaml")

from ducta.api.repositories.v2_store import (  # noqa: E402
    V2ProjectStore,
    _restore_blank_lines,
    _style_of,
)

DEMOS = Path.home() / "Desktop" / "demo_ducta" / "projects"


def _copy(name: str, tmp_path: Path) -> Path:
    src = DEMOS / name
    dest = tmp_path / name
    shutil.copytree(
        src, dest, ignore=shutil.ignore_patterns("data", ".ducta", "logs", "models", "lib", ".env")
    )
    return dest


@pytest.mark.skipif(not DEMOS.is_dir(), reason="demo_ducta projects not on this machine")
@pytest.mark.parametrize("name", ["batch", "streaming", "hybrid"])
def test_set_then_undo_is_byte_identical(name, tmp_path):
    root = _copy(name, tmp_path)
    store = V2ProjectStore.detect(root)
    assert store is not None
    for pipeline, spec in store.pipelines().items():
        path = store.pipeline_path(pipeline)
        before = path.read_text()
        for node in spec.get("nodes") or []:
            version, inverse = store.apply_pipeline_ops(
                pipeline, [{"op": "set", "node": node, "key": "retry", "value": 3}]
            )
            store.apply_pipeline_ops(pipeline, inverse, version)
            assert path.read_text() == before, f"{path.name} changed after editing {node}"


@pytest.mark.skipif(not DEMOS.is_dir(), reason="demo_ducta projects not on this machine")
@pytest.mark.parametrize("name", ["batch", "streaming", "hybrid"])
def test_add_node_then_undo_is_byte_identical(name, tmp_path):
    from ducta.api.repositories.pipeline_ops import apply_op
    from ducta.api.repositories.v2_store import _dump_rt, _load_rt

    root = _copy(name, tmp_path)
    for path in sorted((root / "pipelines").rglob("*.yaml")):
        before = path.read_text()
        doc = _load_rt(path)
        inverse = apply_op(
            doc, {"op": "add_node", "node": "zz.added", "run": "src.m:f", "outputs": ["x"]}
        )
        _dump_rt(path, doc)
        doc = _load_rt(path)
        apply_op(doc, inverse)
        _dump_rt(path, doc)
        assert path.read_text() == before, path.name


def test_indentation_is_read_from_the_file():
    indented = "a:\n  rules:\n    - x\n    - y\n  b: 1\n"
    flush = "a:\n  rules:\n  - x\n  b: 1\n"
    assert _style_of(indented) == {"mapping": 2, "sequence": 4, "offset": 2}
    assert _style_of(flush) == {"mapping": 2, "sequence": 2, "offset": 0}


def test_blank_lines_dropped_on_dump_come_back():
    original = "a:\n  - x\n\nb: 1\n\n\nc: 2\n"
    dumped = "a:\n  - x\nb: 1\nc: 2\n"
    assert _restore_blank_lines(original, dumped) == original
