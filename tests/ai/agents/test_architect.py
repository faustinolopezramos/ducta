"""Ducta Architect: a blueprint checked without a model, designed, built, applied."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

from ducta.ai.agents.architect.blueprint import load_blueprint
from ducta.ai.agents.architect.build import build, module_problems
from ducta.ai.agents.architect.design import NeedsAnswers, blueprint_of, check, design
from ducta.ai.builder import apply_draft, load_draft, revise, save_draft
from ducta.ai.errors import AIConfigError, AIConflictError

sys.path.insert(0, str(Path(__file__).parents[1]))
from test_builder import FakeProvider  # noqa: E402

SALES = (
    Path(__file__).parents[3]
    / "src"
    / "ducta"
    / "skills"
    / "ducta"
    / "assets"
    / "examples"
    / "sales"
)

BLUEPRINT = """\
name: store_revenue
goal: Revenue per store and day
datasets:
  silver.sales.orders_by_store:
    description: One row per order with its store
    format: delta
    keys: [order_id]
    write: merge
    columns: {order_id: bigint, store_id: string, amount: double, order_date: date}
    not_null: [order_id, store_id]
  gold.sales.store_revenue:
    description: Revenue per store and day
    columns: {store_id: string, order_date: date, revenue: double}
pipelines:
  silver.stores:
    description: Attach stores to orders
    owner: data-team
    nodes:
      orders_with_store:
        inputs: {orders: silver.sales.orders}
        outputs: [silver.sales.orders_by_store]
        logic: store_id is the first three characters of order_id
  gold.stores:
    description: Revenue per store
    owner: data-team
    nodes:
      store_revenue:
        inputs: {orders: silver.sales.orders_by_store}
        outputs: [gold.sales.store_revenue]
        logic: sum amount by store_id and order_date
"""

SILVER = """\
```python file=pipelines/silver_stores.py
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def orders_with_store(orders: DataFrame, **kwargs) -> DataFrame:
    return orders.withColumn("store_id", F.substring("order_id", 1, 3))
```"""

GOLD = """\
```python file=pipelines/gold_stores.py
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def store_revenue(orders: DataFrame, **kwargs) -> DataFrame:
    return orders.groupBy("store_id", "order_date").agg(F.sum("amount").alias("revenue"))
```"""


@pytest.fixture
def sales(tmp_path):
    root = tmp_path / "sales"
    shutil.copytree(SALES, root)
    return root


def _answer(body: str = BLUEPRINT) -> str:
    return f"```yaml blueprint\n{body}```\nTwo pipelines, one per layer."


# ── checking, without a model ───────────────────────────────────────────────


def test_a_good_blueprint_checks_and_renders(sales):
    report = check(sales, BLUEPRINT)
    assert report.ok, report.errors
    assert set(report.files) == {
        "catalog.yaml",
        "pipelines/silver.stores.yaml",
        "pipelines/silver_stores.py",
        "pipelines/gold.stores.yaml",
        "pipelines/gold_stores.py",
    }
    gold = yaml.safe_load(report.files["pipelines/gold.stores.yaml"])
    assert gold["depends_on"] == ["silver.stores"]
    assert gold["nodes"]["store_revenue"]["run"] == "pipelines.gold_stores:store_revenue"
    silver = yaml.safe_load(report.files["pipelines/silver.stores.yaml"])
    checks = silver["nodes"]["orders_with_store"]["quality"]["checks"]
    assert checks["null_rate"] == {"columns": ["order_id", "store_id"], "threshold": 0.0}
    assert checks["duplicates"]["columns"] == ["order_id"]  # merge keys are unique
    catalog = yaml.safe_load(report.files["catalog.yaml"])
    assert catalog["silver.sales.orders_by_store"]["write"] == {
        "mode": "merge",
        "merge": {"keys": ["order_id"]},
    }
    assert "format" not in catalog["gold.sales.store_revenue"]  # the project's default gives it


@pytest.mark.parametrize(
    "change, expected",
    [
        ("inputs: {orders: silver.sales.orders}", "inputs: {orders: gold.sales.daily_revenue}"),
        ("name: store_revenue", "name: store_revenue\nextra: 1"),
        ("write: merge", "write: upsert"),
        ("outputs: [gold.sales.store_revenue]", "outputs: [gold.sales.daily_revenue]"),
    ],
)
def test_broken_blueprints_say_why(sales, change, expected):
    report = check(sales, BLUEPRINT.replace(change, expected, 1))
    assert not report.ok and report.errors


def test_merge_needs_delta(sales):
    text = BLUEPRINT.replace("    format: delta\n", "")
    assert any("merges only Delta" in e for e in check(sales, text).errors)


def test_layers_only_flow_upwards(sales):
    text = BLUEPRINT.replace(
        "inputs: {orders: silver.sales.orders}", "inputs: {orders: gold.sales.daily_revenue}"
    )
    assert any("lower layer" in e for e in check(sales, text).errors)


def test_append_is_allowed_with_a_warning(sales):
    text = BLUEPRINT.replace("write: merge", "write: append")
    report = check(sales, text)
    assert report.ok and any("Sentinel never retries" in w for w in report.warnings)


# ── design ──────────────────────────────────────────────────────────────────


def test_design_returns_a_blueprint_draft_that_is_never_applied(sales):
    draft = design(sales, "revenue per store", FakeProvider(_answer()))
    assert draft.ok and draft.kind == "blueprint"
    assert blueprint_of(draft).name == "store_revenue"
    with pytest.raises(AIConflictError, match="build it first"):
        apply_draft(sales, draft)


def test_design_sends_problems_back(sales):
    bad = BLUEPRINT.replace("write: merge", "write: upsert")
    provider = FakeProvider(_answer(bad), _answer())
    draft = design(sales, "revenue per store", provider)
    assert draft.ok and len(draft.attempts) == 2
    assert "write is one of" in provider.calls[1][-1].content


def test_the_model_may_ask_first(sales):
    asking = "```yaml questions\nquestions:\n  - What identifies a store?\n```"
    with pytest.raises(NeedsAnswers) as e:
        design(sales, "revenue per store", FakeProvider(asking))
    assert e.value.questions == ["What identifies a store?"]


def test_a_blueprint_can_be_revised(sales):
    draft = design(sales, "revenue per store", FakeProvider(_answer()))
    save_draft(sales, draft)
    renamed = BLUEPRINT.replace("name: store_revenue", "name: store_revenue_v2")
    revised = revise(
        sales, load_draft(sales, draft.id), "rename it", FakeProvider(_answer(renamed))
    )
    assert revised.kind == "blueprint" and blueprint_of(revised).name == "store_revenue_v2"


# ── build ───────────────────────────────────────────────────────────────────


def test_build_writes_each_module_and_applies(sales):
    bp, _ = load_blueprint(BLUEPRINT)
    provider = FakeProvider(SILVER, GOLD)
    draft = build(sales, bp, provider, blueprint_id="bp1")
    assert draft.ok, draft.blocking
    assert draft.kind == "architect" and draft.target == "bp1"
    assert "withColumn" in draft.files["pipelines/silver_stores.py"]
    written = apply_draft(sales, draft)
    assert "pipelines/gold.stores.yaml" in written
    assert (sales / "pipelines" / "gold_stores.py").read_text().count("groupBy") == 1


def test_build_rejects_a_module_that_reads_files_or_changes_signatures(sales):
    bp, _ = load_blueprint(BLUEPRINT)
    io = SILVER.replace(
        'return orders.withColumn("store_id", F.substring("order_id", 1, 3))',
        'orders.toPandas().to_csv("x.csv")\n    return orders',
    )
    renamed = SILVER.replace("orders: DataFrame, **kwargs", "df: DataFrame, **kwargs")
    provider = FakeProvider(io, renamed, SILVER, GOLD)
    draft = build(sales, bp, provider, max_attempts=3)
    assert draft.ok
    feedback = [c[-1].content for c in provider.calls[1:3]]
    assert "to_csv" in feedback[0] or "brings every row" in feedback[0]
    assert "signature exactly" in feedback[1]


def test_a_failed_build_keeps_the_stubs_and_says_so(sales):
    bp, _ = load_blueprint(BLUEPRINT)
    draft = build(sales, bp, FakeProvider("no code", "still none"), max_attempts=2)
    assert not draft.ok
    assert any("Not built yet" in p["message"] for p in draft.blocking)


def test_module_problems_need_every_function():
    bp, _ = load_blueprint(BLUEPRINT)
    pipe = bp.pipelines["silver.stores"]
    assert module_problems("x = 1\n", "m.py", pipe) == [
        "m.py: `def orders_with_store(orders, **kwargs)` is missing"
    ]


def test_an_architect_draft_is_revised_through_its_blueprint(sales):
    bp, _ = load_blueprint(BLUEPRINT)
    draft = build(sales, bp, FakeProvider(SILVER, GOLD), blueprint_id="bp1")
    with pytest.raises(AIConfigError, match="revise the blueprint"):
        revise(sales, draft, "more", FakeProvider())


# ── names that would collide (2026-10-15 analysis) ──────────────────────────


def test_two_nodes_never_share_a_function(sales):
    text = BLUEPRINT.replace("orders_with_store:", "orders.attach:").replace(
        "store_revenue:\n        inputs", "revenue.attach:\n        inputs"
    )
    # Different pipelines: different modules, so the same function name is fine.
    assert check(sales, text).ok, check(sales, text).errors
    text = (
        BLUEPRINT.replace(
            "        logic: store_id is the first three characters of order_id\n",
            "        logic: store_id is the first three characters of order_id\n"
            "      stores.attach:\n"
            "        inputs: {orders: silver.sales.orders}\n"
            "        outputs: [silver.sales.store_list]\n"
            "        logic: distinct store_id\n",
        )
        .replace("orders_with_store:", "orders.attach:")
        .replace(
            "  gold.sales.store_revenue:",
            "  silver.sales.store_list:\n    description: The stores\n  gold.sales.store_revenue:",
        )
    )
    errors = check(sales, text).errors
    assert any("would both run attach()" in e for e in errors), errors


def test_two_pipelines_never_share_a_module(sales):
    text = BLUEPRINT.replace("  gold.stores:", "  silver_stores:")
    errors = check(sales, text).errors
    assert any("would share the module silver_stores.py" in e for e in errors), errors


def test_a_blueprint_never_overwrites_an_existing_module(sales):
    (sales / "pipelines" / "silver_stores.py").write_text("x = 1\n")
    errors = check(sales, BLUEPRINT).errors
    assert any("silver_stores.py already exists" in e for e in errors), errors


@pytest.mark.parametrize(
    "change, expected",
    [
        ("orders_with_store:", "class:"),
        ("inputs: {orders: silver.sales.orders}", "inputs: {from: silver.sales.orders}"),
        ("inputs: {orders: silver.sales.orders}", "inputs: {kwargs: silver.sales.orders}"),
    ],
)
def test_names_python_cannot_take_are_refused(sales, change, expected):
    errors = check(sales, BLUEPRINT.replace(change, expected, 1)).errors
    assert any("keyword" in e or "parameter name" in e for e in errors), errors


def test_helpers_and_module_level_code_are_reviewed_too():
    bp, _ = load_blueprint(BLUEPRINT)
    pipe = bp.pipelines["silver.stores"]
    helper = (
        "def _all(df):\n    return df.collect()\n\n\n"
        "def orders_with_store(orders, **kwargs):\n    _all(orders)\n    return orders\n"
    )
    assert any("collect()" in p for p in module_problems(helper, "m.py", pipe))
    top = 'import pandas as pd\nLOOKUP = pd.read_csv("stores.csv")\n\n\n' + (
        "def orders_with_store(orders, **kwargs):\n    return orders\n"
    )
    assert any("read_csv" in p for p in module_problems(top, "m.py", pipe))


def test_not_built_lists_only_pipelines_with_code(sales):
    text = BLUEPRINT.replace(
        "pipelines:\n",
        "pipelines:\n"
        "  bronze.extra:\n"
        "    nodes:\n"
        "      land_extra:\n"
        "        kind: ingest\n"
        "        ingest: {source: shop_db, table: public.extra}\n"
        "        outputs: [bronze.sales.extra]\n",
    ).replace("datasets:\n", "datasets:\n  bronze.sales.extra:\n    description: Extra rows\n", 1)
    bp, problems = load_blueprint(text)
    assert not problems
    draft = build(sales, bp, FakeProvider("no code", "still none"), max_attempts=2)
    message = next(p["message"] for p in draft.blocking if "Not built yet" in p["message"])
    assert "bronze_extra" not in message and "silver_stores.py" in message
