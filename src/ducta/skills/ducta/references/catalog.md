# The catalog: every dataset, once

Every dataset the project reads or writes is declared **once**, in `catalog.yaml` or in
a `catalog/` folder (never both). Nodes refer to datasets by name.

```yaml
# catalog.yaml
orders_raw:
  description: Orders as exported by the shop
  format: csv
  path: ${paths.input}/orders.csv
  options: {header: true}
  incremental: {column: order_date}      # read + fingerprint only the run's window
  quality:                               # contract: checked wherever it is read
    empty_dataset: true
    schema: {expected_columns: [order_id, amount, order_date]}

silver.sales.orders:                     # no path: <paths.output>/<env>/silver/sales/orders
  format: delta
  write:
    mode: merge
    merge: {keys: [order_id]}

gold.sales.daily:
  format: parquet
  write: {mode: overwrite, partition: [order_date]}
```

## Keys

| Key | Meaning |
|---|---|
| `format` | required: `csv`, `json`, `parquet`, `delta`, `orc`, `avro`, `xml`, `query` (SQL/JDBC), `pickle`; `unity_catalog` for outputs registered in Unity Catalog |
| `path` | file, directory or URI — optional for a three-part name (below) |
| `table` | a metastore / Unity Catalog table instead of a path |
| `options` | reader options passed to Spark as-is (`header`, `sep`, `mergeSchema`…); CSV defaults to `multiLine: true` (one partition per file: `multiLine: false` on a large file with no line breaks in values) |
| `schema` | a DDL string applied when reading: `"order_id BIGINT, amount DOUBLE"` |
| `incremental` | `{column: …}` — the read is filtered to `--start-date`/`--end-date` on that column |
| `read` | Delta time travel: `{version: 12}` or `{timestamp: "2026-01-31"}` |
| `write` | how a node writes it — below |
| `quality` | the dataset's contract — see [quality](quality.md) |
| `description`, `metadata` | documentation |

## Where a dataset lives

A dataset without `path`/`table` whose name has three parts `schema.sub_folder.table`
lives at `<paths.output>/<env>/<schema>/<sub_folder>/<table>`: `silver.sales.orders` is
`data/dev/silver/sales/orders` under `--env dev` and `data/prod/…` under prod.
Environments can then never overwrite each other's data. Any other name needs a
`path` (or `table`, or `format: query`).

`paths.output` may be a cloud URI (`s3://`, `s3a://`, `gs://`, `abfss://`, `wasbs://`,
`hdfs://`, `dbfs:/`…). Ducta's own state (certificates, chain state, locks) then stays
local in `.ducta/<env>/…`; `run_lock: {backend: storage}` keeps the lock on the bucket.

## Writing

```yaml
silver.sales.customers:
  format: delta
  write:
    mode: merge                          # overwrite (default) | append | ignore | error | merge
    merge:
      keys: [customer_id]
      when_matched: update_all           # update_all | ignore | {update: [cols]}
      when_not_matched: insert_all       # insert_all | ignore
      delete_when: "src._deleted = true"
    partition: [country]
```

- `merge` is an upsert on `keys` for Delta (needs the `delta` extra); a batch with
  duplicate keys fails naming them; the first run creates the table.
- Replace only one slice of a Delta table: `overwrite_strategy: replaceWhere` with
  `partition_col` or `replace_predicate`; without either window it is the run's
  `--start-date`/`--end-date`.
- Replace only the partitions a run wrote in a Parquet/CSV/JSON/ORC output:
  `partition_overwrite: dynamic` (needs `partition` and `mode: overwrite`). The default
  overwrite is `static`: it replaces the whole dataset, so a daily load leaves one day.
  `ducta config validate` warns about that case.
- `incremental: {column: …}` reads only the run's window; `--end-date` is the last day,
  whole, on a date or a timestamp column.
- `write.options` holds writer options that differ from the reader's `options`.
- `write.overwrite_schema` (Delta, default `false`): an overwrite whose columns differ
  from the table's (missing, added, retyped) fails and writes nothing; `true` replaces
  the schema on purpose.
- `write.allow_empty` (default `false`): 0 rows never overwrite a dataset that holds
  data — the node fails; set `true` when an empty result is valid.
- A node with several outputs checks they are all writable before writing any; a
  failure halfway is listed in the certificate's evidence gaps.
- **Re-runs must be safe:** `append` duplicates on every retry — prefer `merge` or
  `replaceWhere` for windowed pipelines.

## A catalog split by layer

```text
catalog/
├── sources.yaml     # raw inputs (names without a layer)
├── bronze.yaml
├── silver.yaml
└── gold.yaml
```

Every file (any depth) is a mapping of dataset names; together they are the catalog.
The same name in two files is an error naming both. `catalog.yaml` next to `catalog/`
is an error.

## Defaults by glob

Shared values go in `ducta.yaml`, applied in order to datasets that do not set them:

```yaml
defaults:
  catalog:
    "bronze.*": {format: parquet}
    "silver.*": {format: delta}
```

## Naming

`layer.domain.table` with layers `seed`, `bronze`, `silver`, `gold`, `ml`
(`silver.sales.orders`). The name documents the dataset and places it on disk.

## Checking

- `ducta config validate` reports a dataset a node uses that is not in the catalog
  (with "did you mean"), a dataset written by two nodes, and datasets that resolve to
  no location.
- `ducta config show --pipeline NAME` shows the datasets one pipeline touches, resolved.
- `ducta config explain catalog.silver.sales.orders.write.mode --env prod` shows where
  a value comes from.
