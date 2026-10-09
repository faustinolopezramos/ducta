"""Canvas edits: small invertible operations on a format-2 pipeline file."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("ruamel.yaml")

from ducta.api.dependencies import get_current_user  # noqa: E402
from ducta.api.main import create_app  # noqa: E402
from ducta.api.models.auth import User  # noqa: E402
from ducta.api.repositories.pipeline_ops import OpError, apply_op, default_alias  # noqa: E402

PIPELINE = """\
# the comment stays
nodes:
  etl.clean:
    run: src.m:clean
    inputs: {orders: raw}   # inline comment
    outputs: [clean]
"""


def _doc(text: str = PIPELINE):
    from ruamel.yaml import YAML

    return YAML().load(text)


def _dump(doc) -> str:
    import io

    from ruamel.yaml import YAML

    buf = io.StringIO()
    YAML().dump(doc, buf)
    return buf.getvalue()


def test_default_alias_is_a_unique_identifier():
    assert default_alias("silver.education.student_cleaned", []) == "student_cleaned"
    assert default_alias("a.orders", ["orders"]) == "orders_2"
    assert default_alias("x.2021", []) == "_2021"


def test_connect_then_its_inverse_leaves_the_file_as_it_was():
    doc = _doc()
    inverse = apply_op(doc, {"op": "connect", "node": "etl.clean", "dataset": "silver.customers"})
    assert dict(doc["nodes"]["etl.clean"]["inputs"]) == {
        "orders": "raw",
        "customers": "silver.customers",
    }
    apply_op(doc, inverse)
    assert _dump(doc) == PIPELINE


def test_remove_node_then_add_it_back():
    doc = _doc()
    inverse = apply_op(doc, {"op": "remove_node", "node": "etl.clean"})
    assert "etl.clean" not in doc["nodes"]
    apply_op(doc, inverse)
    assert doc["nodes"]["etl.clean"]["run"] == "src.m:clean"


def test_set_and_unset_a_key():
    doc = _doc()
    inverse = apply_op(doc, {"op": "set", "node": "etl.clean", "key": "retry", "value": 2})
    assert doc["nodes"]["etl.clean"]["retry"] == 2
    assert inverse == {"op": "set", "node": "etl.clean", "key": "retry", "value": None}
    apply_op(doc, inverse)
    assert "retry" not in doc["nodes"]["etl.clean"]


@pytest.mark.parametrize(
    "op",
    [
        {"op": "connect", "node": "etl.clean", "dataset": "raw"},
        {"op": "disconnect", "node": "etl.clean", "dataset": "nope"},
        {"op": "set", "node": "etl.clean", "key": "inputs", "value": {}},
        {"op": "add_node", "node": "etl.clean"},
        {"op": "teleport", "node": "etl.clean"},
        {"op": "connect", "node": "missing", "dataset": "x"},
    ],
)
def test_operations_that_do_not_apply_are_refused(op):
    with pytest.raises(OpError):
        apply_op(_doc(), op)


# ── through the API ──────────────────────────────────────────────────────────


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="admin", username="admin", email="admin@example.com", roles=["admin"]
    )
    return TestClient(app)


@pytest.fixture
def root(tmp_path, monkeypatch) -> Path:
    from ducta.console.template import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    return root


def _post(root, body):
    return _client().post(
        "/api/projects/proj/pipelines/etl/ops", params={"source": str(root)}, json=body
    )


def test_add_a_node_with_a_new_dataset_then_undo(root):
    from ducta.api.repositories.v2_store import V2ProjectStore

    etl = root / "pipelines" / "etl.yaml"
    before = etl.read_text()
    store = V2ProjectStore.detect(root)
    a_dataset = next(iter(store.project().catalog))
    r = _post(
        root,
        {
            "ops": [
                {
                    "op": "add_node",
                    "node": "etl.extra",
                    "run": "pipelines.etl:clean",
                    "inputs": {"df": a_dataset},
                    "outputs": ["silver.etl.extra"],
                }
            ],
            "new_datasets": {"silver.etl.extra": {"format": "parquet"}},
        },
    )
    assert r.status_code == 200, r.text
    assert "etl.extra" in etl.read_text()
    assert "silver.etl.extra" in V2ProjectStore.detect(root).project().catalog

    undo = _post(root, {"ops": r.json()["inverse"], "expected_version": r.json()["version"]})
    assert undo.status_code == 200, undo.text
    assert etl.read_text() == before


def test_an_edit_that_breaks_the_project_is_refused_and_restored(root):
    etl = root / "pipelines" / "etl.yaml"
    before = etl.read_text()
    node = next(n for n in __import__("yaml").safe_load(before)["nodes"])
    r = _post(root, {"ops": [{"op": "connect", "node": node, "dataset": "no.such.dataset"}]})
    assert r.status_code == 400
    assert etl.read_text() == before


def test_add_node_from_a_template():
    doc = _doc()
    inverse = apply_op(
        doc,
        {
            "op": "add_node",
            "node": "etl.dedupe",
            "use": "dedupe_by_key",
            "with": {"key": "id"},
            "inputs": {"df": "clean"},
            "outputs": ["deduped"],
        },
    )
    node = doc["nodes"]["etl.dedupe"]
    assert list(node) == ["use", "with", "inputs", "outputs"]
    assert node["with"] == {"key": "id"}
    apply_op(doc, inverse)
    assert _dump(doc) == PIPELINE
