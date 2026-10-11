# Pipelines and nodes

One file per pipeline under `pipelines/`; **the file name is the pipeline name**
(`pipelines/silver.sales.yaml` → pipeline `silver.sales`).

```yaml
# pipelines/etl.yaml
description: Orders to daily totals
requires_dates: true                 # default true: runs need --start-date/--end-date
depends_on: [bronze.sales]           # pipelines that must run first
nodes:
  clean:
    run: pipelines.etl:clean         # module:function, imported from the project root
    inputs: {raw: orders_raw}        # function parameter -> catalog dataset
    outputs: [silver.sales.orders]
    quality:
      checks:
        null_rate: {columns: [order_id], threshold: 0}
      gate: {max_errors: 0, on_fail: skip_downstream}
  daily:
    run: pipelines.etl:daily
    inputs: {orders: silver.sales.orders}   # runs after `clean`: inferred from the data
    outputs: [gold.sales.daily]
    timeout_seconds: 600
    retry: 1
```

```python
# pipelines/etl.py — plain functions, no Ducta imports needed
from pyspark.sql import DataFrame, functions as F

def clean(raw: DataFrame) -> DataFrame:
    return raw.dropDuplicates(["order_id"]).filter(F.col("amount") > 0)

def daily(orders: DataFrame) -> DataFrame:
    return orders.groupBy("order_date").agg(F.sum("amount").alias("revenue"))
```

## Pipeline keys

| Key | Meaning |
|---|---|
| `nodes` | the nodes, by name |
| `type` | `batch` (default), `ml`, `streaming`, `hybrid` |
| `requires_dates` | `true` (default) — set `false` for pipelines that process everything |
| `depends_on` | pipelines to run before this one (a chain); with `reuse_if_materialized: true` an upstream whose outputs are still valid is skipped |
| `spark_config` | Spark settings for this pipeline only |
| `split`, `hyperparams`, `hyperparams_config`, `model_version` | ML — see [mlops](mlops.md) |
| `extends`, `params` | build on a template — see [project-format](project-format.md) |
| `defaults` | node defaults for this pipeline |
| `description`, `metadata` | documentation; not read |

## Node keys (`kind: transform`, the default)

| Key | Meaning |
|---|---|
| `run` | `package.module:function` |
| `inputs` | `{parameter: dataset}` (preferred) or `[dataset, …]` passed positionally |
| `outputs` | datasets the returned DataFrame is written to (several = same result to each) |
| `after` | nodes to run first when no dataset connects them |
| `quality` | checks on the output and the gate — see [quality](quality.md) |
| `input_checks` | `{dataset: {checks: …}}` — checks on one input for this node only |
| `timeout_seconds` | this node's limit (overrides `node_timeout_seconds`) |
| `retry` | retries after a failure (0–10, default 0) |
| `run_in_process` | run in its own process, so a timeout can stop pure-Python code |
| `on_missing_input` | `skip` (default: node and dependants skipped) or `fail` |
| `fail_fast` | stop checking at the first failing check |
| `ml_stage`, `split`, `hyperparams`, `model_version`, `model`, `metrics` | ML — see [mlops](mlops.md) |
| `description`, `metadata` | documentation; not read |

Rules the validator enforces:

- **Node names are unique across the whole project**, and a node belongs to one pipeline.
- Every dataset in `inputs`/`outputs` must be in the catalog.
- Each `inputs` key must be a **parameter of the function** (checked by
  `ducta config validate` without running anything). Ducta also passes `start_date`
  and `end_date` (the run's window) and, in ML pipelines, `ml_context`, to a function
  that declares them or takes `**kwargs`.
- A dataset is written by one node only.
- No cycles — through data, `after`, or `depends_on`.
- Order comes from the data: nodes with no path between them run in parallel.

## Other node kinds (no Python)

**Ingest** — copy a table from a database connection (see [ingestion](ingestion.md)):

```yaml
land_orders:
  kind: ingest
  ingest:
    source: shop_db                 # a connection in sources.yaml
    table: public.orders            # or query: "SELECT …"
    columns: [order_id, amount, order_date]
    where: "order_date >= '2026-01-01'"
  outputs: [bronze.shop.orders]
```

**Stream** — Structured Streaming (see [streaming](streaming.md)): `kind: stream` with a
`stream:` block (`input`, `transform`, `model`, `output`, `streaming`).

Each kind accepts only its own keys: an `ingest` node with `run:` is an error.

## Adding a node — checklist

1. Reuse existing datasets as inputs; check `ducta config show --pipeline NAME`.
2. Name it `verb_object` (`clean_orders`), unique in the project.
3. Declare new outputs in the catalog (`layer.domain.table` needs no `path`).
4. Write the function with one parameter per `inputs` key (add `start_date`,
   `end_date` or `ml_context` only if it needs them).
5. `ducta config validate --env dev --output-format json`, then run it alone:
   `ducta start --env dev --pipeline NAME --node NODE [dates]`.

## Testing node functions

Functions are plain Python, so test them with small DataFrames:

```python
# tests/test_etl.py
import pytest
from pyspark.sql import SparkSession
from pipelines.etl import clean

@pytest.fixture(scope="session")
def spark():
    return SparkSession.builder.master("local[1]").getOrCreate()

def test_clean_drops_duplicates(spark):
    df = spark.createDataFrame([(1, 10.0), (1, 10.0), (2, -5.0)], ["order_id", "amount"])
    assert [r.order_id for r in clean(df).collect()] == [1]
```
