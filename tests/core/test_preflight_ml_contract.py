"""`ducta config validate` catches an ML contract that cannot be kept, before any data.

A split nobody is bound to apply, or a bound node whose function cannot receive
`ml_context`, used to surface only at run time (or not at all).
"""

from __future__ import annotations

import itertools
import textwrap

import pytest

from ducta.core import preflight
from ducta.setting.project_loader import load_project_v2

_ids = itertools.count()

WITH_CTX = "def train(raw, ml_context=None):\n    return raw\n"
WITHOUT_CTX = "def train(raw):\n    return raw\n"


@pytest.fixture(scope="module")
def _code_root(tmp_path_factory):
    """One `custom_nodes` package for the whole module (an allowed module prefix);
    each test adds its own module to it, so the import cache never gets in the way."""
    import sys

    base = tmp_path_factory.mktemp("code")
    (base / "custom_nodes").mkdir()
    (base / "custom_nodes" / "__init__.py").write_text("")
    sys.path.insert(0, str(base))
    yield base / "custom_nodes"
    sys.path.remove(str(base))
    for name in [m for m in sys.modules if m == "custom_nodes" or m.startswith("custom_nodes.")]:
        del sys.modules[name]


@pytest.fixture(autouse=True)
def _code(_code_root, monkeypatch):
    monkeypatch.setattr(_report, "code_root", _code_root, raising=False)


def _report(tmp_path, monkeypatch, node_yaml, pipeline_extra="", code=WITH_CTX, settings=""):
    name = f"mlc_{next(_ids)}"
    (_report.code_root / f"{name}.py").write_text(code)
    module = f"custom_nodes.{name}"
    root = tmp_path / "proj"
    (root / "pipelines").mkdir(parents=True)
    (root / "ducta.yaml").write_text(
        "version: 2\nproject: p\npaths: {input: d, output: o}\n" + settings
    )
    (root / "catalog.yaml").write_text("d: {format: csv, path: d.csv}\nml.x.o: {format: parquet}\n")
    node = textwrap.dedent(node_yaml).replace("MODULE", module)
    (root / "pipelines" / "p.yaml").write_text(
        "type: ml\nrequires_dates: false\n"
        + pipeline_extra
        + "nodes:\n"
        + textwrap.indent(node, "  ")
    )
    return preflight.validate_pipeline(load_project_v2(root, None), "p")


NODE = """\
train:
  run: MODULE:train
  inputs: {raw: d}
  outputs: [ml.x.o]
"""
SPLIT = "split: {method: random, test_size: 0.2, seed: 1}\n"


def test_a_pipeline_split_with_a_training_node_that_can_apply_it_passes(tmp_path, monkeypatch):
    report = _report(tmp_path, monkeypatch, NODE + "  ml_stage: training\n", SPLIT)
    assert report.ok, report.errors


def test_a_pipeline_split_nobody_is_bound_to_apply_is_an_error(tmp_path, monkeypatch):
    report = _report(tmp_path, monkeypatch, NODE, SPLIT)
    assert any("no node is bound to apply it" in e for e in report.errors)
    assert any("ml_stage: training" in e for e in report.errors)


def test_a_bound_node_that_cannot_receive_ml_context_is_an_error(tmp_path, monkeypatch):
    report = _report(
        tmp_path, monkeypatch, NODE + "  ml_stage: training\n", SPLIT, code=WITHOUT_CTX
    )
    assert any("takes no `ml_context`" in e for e in report.errors)


def test_a_node_with_its_own_split_must_be_able_to_receive_it(tmp_path, monkeypatch):
    report = _report(tmp_path, monkeypatch, NODE + "  " + SPLIT, code=WITHOUT_CTX)
    assert any("takes no `ml_context`" in e for e in report.errors)


def test_a_node_split_counts_as_bound_without_a_stage(tmp_path, monkeypatch):
    report = _report(tmp_path, monkeypatch, NODE + "  " + SPLIT)
    assert report.ok, report.errors


def test_kwargs_is_enough_to_receive_ml_context(tmp_path, monkeypatch):
    code = "def train(raw, **kwargs):\n    return raw\n"
    report = _report(tmp_path, monkeypatch, NODE + "  ml_stage: training\n", SPLIT, code=code)
    assert report.ok, report.errors


def test_with_split_enforcement_warn_they_are_warnings(tmp_path, monkeypatch):
    report = _report(
        tmp_path, monkeypatch, NODE, SPLIT, settings="settings: {split_enforcement: warn}\n"
    )
    assert report.ok
    assert any("no node is bound to apply it" in w for w in report.warnings)


def test_an_unknown_enforcement_value_is_rejected_when_the_project_loads(tmp_path, monkeypatch):
    from ducta.setting.project_loader import ProjectConfigError

    with pytest.raises(ProjectConfigError, match="split_enforcement"):
        _report(tmp_path, monkeypatch, NODE, settings="settings: {split_enforcement: never}\n")
