"""Adding nodes to an existing pipeline, and reviewing a whole pipeline.

An extension may only add: every existing node, setting and statement of the
pipeline's modules must come back unchanged — Ducta checks it without a model,
sends what it finds back to the model, and asks again when the draft is
applied. A pipeline's review holds the model's findings to the node and line
they name, like a node's review.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.ai.builder import apply_draft, revise, save_draft
from ducta.ai.errors import AIConfigError, AIConflictError
from ducta.ai.extend import existing_changes, extend
from ducta.ai.pipeline_review import (
    load_pipeline_review,
    review_pipeline,
    save_pipeline_review,
)

sys.path.insert(0, str(Path(__file__).parent))
from test_builder import FakeProvider  # noqa: E402

SALES = (
    Path(__file__).parents[2]
    / "src"
    / "ducta"
    / "skills"
    / "ducta"
    / "assets"
    / "examples"
    / "sales"
)
NEW_NODE = """  latest_customers:
    description: One row per customer, latest order wins
    run: pipelines.sales:latest_customers
    inputs: {orders: silver.sales.orders}
    outputs: [silver.sales.customers]
"""
NEW_FUNCTION = """

def latest_customers(orders, **kwargs):
    return orders.dropDuplicates(["order_id"])
"""
CATALOG = "```yaml catalog\nsilver.sales.customers: {description: One row per customer}\n```"


@pytest.fixture
def sales(tmp_path):
    root = tmp_path / "sales"
    shutil.copytree(SALES, root)
    return root


def _pipeline(root: Path) -> str:
    return (root / "pipelines" / "silver.sales.yaml").read_text()


def _module(root: Path) -> str:
    return (root / "pipelines" / "sales.py").read_text()


def _answer(pipeline: str, module: str, catalog: str = CATALOG) -> str:
    return (
        f"```yaml file=pipelines/silver.sales.yaml\n{pipeline.rstrip()}\n```\n"
        f"```python file=pipelines/sales.py\n{module.rstrip()}\n```\n{catalog}\n"
        "Adds latest_customers."
    )


def _good(root: Path) -> str:
    return _answer(_pipeline(root).rstrip() + "\n" + NEW_NODE, _module(root) + NEW_FUNCTION)


# ── adding nodes ────────────────────────────────────────────────────────────


def test_new_nodes_are_added_and_nothing_else_changes(sales):
    before = _pipeline(sales)
    draft = extend(
        sales, "silver.sales", "a node with one row per customer", FakeProvider(_good(sales))
    )
    assert draft.ok, draft.blocking
    assert draft.kind == "extend" and draft.pipeline == "silver.sales"
    text = draft.files["pipelines/silver.sales.yaml"]
    # Ducta wrote the pipeline file: the original, as it was, then the new node.
    assert text.startswith(before.rstrip("\n")) and "latest_customers:" in text
    assert "def latest_customers" in draft.files["pipelines/sales.py"]
    assert draft.new_datasets == ["silver.sales.customers"]
    assert [
        ln
        for ln in draft.diff(sales).splitlines()
        if ln.startswith("-") and not ln.startswith("---")
    ] == []
    apply_draft(sales, draft)
    assert "latest_customers" in _pipeline(sales)


@pytest.mark.parametrize(
    "spoil, expected",
    [
        (
            lambda p, m: (p.replace("clean_orders:", "clean_orders_v2:"), m),
            "node clean_orders is missing",
        ),
        (
            lambda p, m: (p.replace("[gold.sales.daily_revenue]", "[gold.sales.revenue]"), m),
            "node daily_revenue changed",
        ),
        (lambda p, m: (p.replace("Clean orders", "Clean the orders"), m), "`description` changed"),
        (
            lambda p, m: (p, m.replace('F.col("amount") > 0', 'F.col("amount") >= 0')),
            "clean_orders() changed",
        ),
    ],
)
def test_an_existing_node_function_or_setting_never_changes(sales, spoil, expected):
    pipeline, module = spoil(
        _pipeline(sales).rstrip() + "\n" + NEW_NODE, _module(sales) + NEW_FUNCTION
    )
    provider = FakeProvider(_answer(pipeline, module), _good(sales))
    draft = extend(sales, "silver.sales", "customers", provider)
    assert draft.ok
    assert any(expected in r for r in draft.attempts[0].rejected), draft.attempts[0].rejected
    # What was wrong went back to the model with the request.
    assert expected in provider.calls[1][-1].content


def test_an_answer_that_adds_no_node_is_sent_back(sales):
    nothing = _answer(
        _pipeline(sales).replace("requires_dates: false", "requires_dates: false\n"), _module(sales)
    )
    draft = extend(sales, "silver.sales", "customers", FakeProvider(nothing, _good(sales)))
    assert draft.ok and len(draft.attempts) == 2


def test_depends_on_may_only_grow(sales):
    text = _pipeline(sales).replace("depends_on: [bronze.sales]", "depends_on: []")
    assert any(
        "depends_on lost bronze.sales" in p
        for p in existing_changes(
            sales, "silver.sales", {"pipelines/silver.sales.yaml": text + NEW_NODE}
        )
    )


def test_an_extension_edited_by_hand_is_refused_even_forced(sales):
    draft = extend(sales, "silver.sales", "customers", FakeProvider(_good(sales)))
    draft.files["pipelines/silver.sales.yaml"] = draft.files["pipelines/silver.sales.yaml"].replace(
        "clean_orders:", "renamed:"
    )
    with pytest.raises(AIConflictError, match="node clean_orders is missing"):
        apply_draft(sales, draft, force=True)


def test_an_extension_can_be_revised(sales):
    first = extend(sales, "silver.sales", "customers", FakeProvider(_good(sales)))
    save_draft(sales, first)
    better = revise(sales, first, "call it customers_latest", FakeProvider(_good(sales)))
    assert better.kind == "extend" and better.revision_of == first.id and better.ok


def test_an_extension_needs_a_request(sales):
    with pytest.raises(AIConfigError):
        extend(sales, "silver.sales", "  ", FakeProvider())


# ── reviewing a whole pipeline ──────────────────────────────────────────────

REVIEW = """```yaml review
findings:
  - node: clean_orders
    severity: high
    area: code
    title: Drops refunds silently
    line: 8
    code: filter(F.col("amount") > 0)
  - node: clean_orders
    severity: low
    area: code
    title: Made up line
    line: 99
  - node: ghost
    severity: low
    area: config
    title: A node it does not have
  - severity: low
    area: config
    title: No SLA
    key: metadata.sla
ideas:
  - Orders per store and day, from silver.sales.orders
  - Customers with their first and last order date
  - Refunds per day, from silver.sales.orders
  - A fourth idea that is one too many
```"""


def test_ducta_reviews_every_node_and_the_pipeline_without_a_model(sales):
    result = review_pipeline(sales, "silver.sales", None)
    titles = {(f.node, f.title) for f in result.findings}
    assert (None, "No owner") in titles
    assert any(t == (None, "2 nodes without a description") for t in titles)
    assert result.model is None and result.nodes == ["clean_orders", "daily_revenue"]
    assert all(f.source == "ducta" for f in result.findings)


def test_the_models_findings_must_name_a_real_node_and_line(sales):
    result = review_pipeline(sales, "silver.sales", FakeProvider(REVIEW))
    ai = [(f.node, f.title, f.line) for f in result.findings if f.source == "ai"]
    assert ("clean_orders", "Drops refunds silently", 8) in ai
    assert (None, "No SLA", None) in ai
    assert result.dropped == 2
    assert len(result.ideas) == 3 and result.ideas[0].startswith("Orders per store")


def test_a_pipeline_review_changes_nothing_and_is_kept(sales):
    before = {p: p.read_text() for p in sales.rglob("*") if p.is_file()}
    result = review_pipeline(sales, "silver.sales", FakeProvider(REVIEW))
    assert {p: p.read_text() for p in sales.rglob("*") if p.is_file()} == before
    save_pipeline_review(sales, result)
    kept = load_pipeline_review(sales, "silver.sales")
    assert kept is not None and kept.to_dict() == result.to_dict()
    assert load_pipeline_review(sales, "bronze.sales") is None


def test_a_pipeline_too_large_for_the_model_is_refused_before_asking(sales, monkeypatch):
    import ducta.ai.pipeline_review as pr

    monkeypatch.setattr(pr, "MAX_PIPELINE_CHARS", 100)
    provider = FakeProvider(REVIEW)
    with pytest.raises(AIConfigError, match="one by one"):
        review_pipeline(sales, "silver.sales", provider)
    assert provider.calls == []


def test_ducta_ai_review_of_a_whole_pipeline(sales, capsys):
    from ducta.console.commands.ai_cmds import AICommands

    args = SimpleNamespace(
        ai_command="review",
        pipeline="silver.sales",
        node=None,
        env="dev",
        note=None,
        no_ai=True,
        fail_on=None,
        base_path=str(sales),
        output_format="json",
    )
    assert AICommands.handle(args) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["kind"] == "pipeline" and doc["nodes"] == ["clean_orders", "daily_revenue"]
    assert load_pipeline_review(sales, "silver.sales") is not None


def test_the_code_an_extension_adds_is_held_to_ductas_review(sales):
    pulls = _answer(
        _pipeline(sales).rstrip() + "\n" + NEW_NODE,
        _module(sales)
        + NEW_FUNCTION.replace(
            "return orders.dropDuplicates", "orders.collect()\n    return orders.dropDuplicates"
        ),
    )
    draft = extend(sales, "silver.sales", "customers", FakeProvider(pulls, _good(sales)))
    assert draft.ok and any("collect()" in r for r in draft.attempts[0].rejected)


def test_what_an_extension_adds_is_summed_up(sales):
    from ducta.ai.extend import extension_summary

    draft = extend(sales, "silver.sales", "customers", FakeProvider(_good(sales)))
    added = extension_summary(sales, draft)
    assert added["nodes"] == [
        {
            "name": "latest_customers",
            "inputs": ["silver.sales.orders"],
            "outputs": ["silver.sales.customers"],
            "description": "One row per customer, latest order wins",
        }
    ]
    assert added["functions"] == ["pipelines/sales.py: latest_customers()"]
    assert added["datasets"] == ["silver.sales.customers"]
