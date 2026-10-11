# Data quality: checks, contracts, gates

## Where checks go

The same block — checks plus an optional `gate` — goes in three places:

| Place | Runs |
|---|---|
| a dataset's `quality` in the catalog | before **every** node that reads it — its **contract** |
| a node's `input_checks: {dataset: {checks: …}}` | before that node only; replaces the contract for it |
| a node's `quality` | after the node, on what it wrote |

```yaml
# catalog.yaml — a contract on data another team produces
orders_raw:
  format: csv
  path: ${paths.input}/orders.csv
  options: {header: true}
  quality:
    fail_fast: true
    empty_dataset: true
    schema: {expected_columns: [order_id, amount, order_date]}
    row_count: {min: 1000}
```

```yaml
# pipelines/etl.yaml — checks on a node's output
clean:
  run: pipelines.etl:clean
  inputs: {raw: orders_raw}
  outputs: [silver.sales.orders]
  quality:
    checks:
      null_rate: {columns: [order_id], threshold: 0}
      duplicates: {columns: [order_id]}
      range: {column: amount, min: 0, max: 1000000}
    gate:
      max_errors: 0
      on_fail: stop_all
```

Checks may also be written directly next to `gate` without `checks:`. `name: true`
enables a check with defaults; `false` disables one (e.g. from a profile). With several
outputs, `dataset_name` picks the one checked (default: the first).

## Built-in checks

`ducta quality list` prints every registered check, including custom ones.

| Category | Checks |
|---|---|
| Structural | `schema` (`expected_columns`, `strict`), `row_count` (`min`, `max`), `null_rate` (`columns`, `threshold`), `empty_dataset`, `duplicates` (`columns`, `max_duplicate_rate`), `range` (`column`, `min`, `max`), `referential_integrity`, `schema_drift` |
| Temporal | `freshness`, `incremental_volume`, `anomaly_detection` (a column's mean vs. its baseline) |
| Distribution | `drift_detection`, `statistical` |
| Cross-table | `cross_table_referential`, `dataset_completeness` |
| Business | `business_rules` — SQL predicates every row must satisfy |
| Model output | `prediction_contract`, `prediction_rate`, `prediction_drift` |

Parameters are validated when the project loads (unknown parameter, wrong type, out of
range, near-miss names). `threshold` for `null_rate` is a share between 0 and 1. A
check naming a column the data does not have **fails**. Checks that compare with
another dataset (`reference_dataset`, `reference`) need it in the catalog.

## Gates

| Key | Blocks when |
|---|---|
| `max_errors` | more error-severity checks fail (default 0: any failing check blocks) |
| `max_warnings` | never blocks; logs when exceeded |
| `min_pass_rate` | the share of passing checks is lower (0.95 = 95 %) |
| `required_checks` | one of these fails or is missing |
| `score_threshold` + `score_weights` | the weighted score (0–1) is lower |

`on_fail`: `skip_downstream` (default — dependants skipped, the run does not fail),
`stop_all` (the run fails), `warn_only`.

Stricter only in production:

```yaml
environments:
  prod:
    pipelines.etl.nodes.clean.quality.gate.on_fail: stop_all
```

## Profiles

Named, reusable check sets in `settings.quality.profiles` or `quality/profiles.yaml`
(not both for the same name). Use with `profile: NAME`; the block's own checks merge on
top. An unknown profile name is an error.

```yaml
# quality/profiles.yaml
keyed:
  checks:
    empty_dataset: {enabled: true}
    duplicates: {columns: [id]}
```

## Starting a contract from real data

```bash
ducta profile --input data/orders.parquet --strictness balanced --output checks.yaml
ducta quality validate-config --node clean --env dev     # check a node's quality block, no data
ducta quality run --input data.parquet --config checks.yaml   # a checks file on a data file
```

`profile` reads the file (parquet, csv, json; no project, no Spark) and proposes the
checks it already satisfies — review before adopting.

## Custom checks

```python
# pipelines/quality_checks.py
from ducta.check import BaseQualityCheck, register_check

@register_check("positive_amounts")
class PositiveAmounts(BaseQualityCheck):
    def __init__(self):
        super().__init__("positive_amounts")

    def _run_impl(self, df, config, adapter, context_datasets=None):
        negatives = adapter.filter_where("amount < 0")   # same SQL on Spark and pandas
        return self._create_result(passed=negatives == 0,
                                   message=f"{negatives} negative amount(s)",
                                   details={"negative_rows": negatives})
```

```yaml
# ducta.yaml
settings:
  quality:
    extensions: [pipelines.quality_checks]
```

The CLI imports extensions; the web server does not (it never runs workspace code).

## Reports

Each run writes `<paths.output>/<env>/quality/<pipeline>/<node>/` (`reports/`,
`gate_results/`, `history.json`, `baseline.json`). Read them with:

```bash
ducta quality report --dataset silver.sales.orders --env dev --pipeline etl   # --all lists run ids
ducta quality trend --dataset silver.sales.orders --env dev --pipeline etl --last 20
ducta quality score --run-id ID --env dev
```

Pass `--pipeline` (the pipeline the node belongs to): reports are scoped per pipeline.
Without `--env`, these commands read the standalone `--workspace` store (`.quality/` of
`ducta quality run`) instead of the project's.

## Good practice

Contracts on inputs you do not control; checks + a gate on outputs others depend on;
choose `on_fail` on purpose; reuse sets through profiles; start from `ducta profile`.
