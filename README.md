<div align="center">

# Ducta

**Build, run, and trust data pipelines — batch, streaming, and machine learning — from simple configuration.**

[![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12%20|%203.13-blue)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange)](CHANGELOG.md)

</div>

Ducta lets you describe a data pipeline in a few config files, write your
transformations as ordinary Python functions, and run them with one command —
locally or on the cloud. Data-quality checks, experiment tracking, and a
tamper-evident record of every run come built in, so you can trust the results.

> **Status:** Alpha (`0.1.0`). Things may change between releases — see the
> [CHANGELOG](CHANGELOG.md).

> **Using Ducta vs. contributing to it.** If you just want to *use* Ducta,
> install the package from PyPI — `pip install ducta` (see [Install](#install)) —
> and you never touch this source tree. **This repository is organized for
> contributors** working on Ducta itself: its layout and tooling are built
> around that — see [Contributing](#contributing) below. The feature sections
> in between explain what Ducta does — useful context whichever side you're on.

---

## Why Ducta

- **One tool for every pipeline** — batch, streaming, and machine learning, the same way.
- **You write plain Python** — Ducta runs your functions in the right order and handles the data plumbing.
- **Runs anywhere** — your laptop (local Spark) or a cluster (Apache Spark / Databricks), no code changes.
- **Quality you can enforce** — automatic checks on your data that can warn or stop a run before bad data spreads.
- **Reproducible & auditable** — every run leaves a signed certificate of what ran, on which data, and with what result.
- **Work how you like** — a command line, a REST API, or a visual web app.

---

## Install

Requires **Python 3.10–3.13**. Once a release is published, the intended
end-user install is:

```bash
pip install "ducta[spark]"        # running pipelines (start here)
pip install "ducta[mlops]"        # + experiment tracking & model registry
pip install "ducta[api]"          # + web app / REST API
pip install "ducta[all]"          # everything above
```

> **Spark is required to run a pipeline.** Bare `pip install ducta` gives you the
> library and the CLI, but every execution context builds a Spark session, so
> commands that load a project (`ducta start`, `ducta config list-pipelines`, …)
> need the `spark` extra. Install `ducta[spark]` unless you only want to import
> Ducta as a library.

> **`databricks` is a separate, mutually exclusive extra.** Use
> `pip install "ducta[databricks]"` *instead of* `[spark]`, never alongside it:
> `databricks-connect` ships its own `pyspark` package and overwrites the real
> one, after which local execution fails. For that reason it is not part of
> `[all]`.

> **Contributing / working from source?** Don't use `pip` — set up the dev
> environment with Poetry (or Docker) instead. See [Contributing](#contributing).

---

## Get started in 5 minutes

Scaffold a ready-to-run project and execute your first pipeline:

```bash
# 1. Create a project (Medallion layout: bronze → silver → gold)
ducta template --template medallion_basic --project-name my_project --format yaml
cd my_project

# 2. See what pipelines it comes with
ducta config list-pipelines

# 3. Run one for a date range
ducta start --env dev --pipeline <pipeline-name> \
  --start-date 2026-01-01 --end-date 2026-01-31
```

Other starting points: `--template ml_ready`, `streaming_core`, or `hybrid`.
Run `ducta --help` to see every command.

---

## Anatomy of a pipeline

A Ducta project is **your transformation code** plus a few **config files** that
wire everything together. Here is a complete, minimal pipeline.

**1. Your transformation** — a normal Python function. Ducta passes in the input
data (a Spark DataFrame) and the run's date range, and you return the result.

```python
# nodes.py
def clean_sales(sales, start_date, end_date):
    return sales.dropna()          # any DataFrame transformation
```

**2. Where the data comes from and goes** (`config/input.yaml`, `config/output.yaml`):

```yaml
# input.yaml
raw_sales:
  format: "csv"
  filepath: "${input_path}/sales.csv"
  options: { header: "true", inferSchema: "true" }
```

```yaml
# output.yaml
core.analytics.sales_clean:
  format: "parquet"
  write_mode: "overwrite"
```

**3. The step and the pipeline** (`config/nodes.yaml`, `config/pipelines.yaml`):

```yaml
# nodes.yaml — one entry per transformation
clean_sales:
  module: "nodes"                 # your nodes.py
  function: "clean_sales"
  input: ["raw_sales"]            # passed to your function, in order
  output: ["core.analytics.sales_clean"]

# pipelines.yaml — order your steps into a pipeline
sales_daily:
  type: batch
  nodes: ["clean_sales"]
```

**4. Run it:**

```bash
ducta start --env dev --pipeline sales_daily \
  --start-date 2026-01-01 --end-date 2026-01-31
```

Ducta reads `raw_sales`, runs `clean_sales`, checks the output, writes
`sales_clean`, and records a run certificate — all from that config.

---

## Enforce data quality

Add checks to any step. A **quality gate** decides whether a failure just warns
or actually stops the run.

```yaml
# nodes.yaml
clean_sales:
  module: "nodes"
  function: "clean_sales"
  input: ["raw_sales"]
  output: ["core.analytics.sales_clean"]
  data_quality:
    checks:
      row_count: { min: 1000 }              # expect at least 1,000 rows
      null_rate: { column: "id", max: 0.0 } # no missing ids
      duplicates: { columns: ["id"] }       # ids must be unique
    quality_gate:
      max_errors: 0                          # any error blocks downstream steps
```

Built-in checks include row counts, null rates, ranges, duplicates, schema,
freshness, and drift — and you can add your own.

---

## Use the web app

Prefer a visual workspace? Launch the built-in server and open it in your browser:

```bash
ducta server start --port 8000
# Web app & API docs:  http://localhost:8000
```

From there you can browse pipelines, edit configuration, launch runs, and watch
logs stream live.

---

## Command cheatsheet

| Command | What it does |
|---------|--------------|
| `ducta template --template medallion_basic --project-name NAME` | Scaffold a new project |
| `ducta config list-pipelines` | List the pipelines in a project |
| `ducta start --env dev --pipeline NAME` | Run a batch / ML pipeline |
| `ducta stream run --pipeline NAME` | Start a streaming pipeline |
| `ducta quality run --input data.parquet --config checks.yaml` | Check a data file's quality |
| `ducta server start --port 8000` | Launch the web app + API |
| `ducta certify verify --run-id RUN_ID` | Verify a run certificate (from `.ducta/runs/`) |
| `ducta --help` | Full command reference |

---

## Contributing

Want to build or contribute to Ducta itself, rather than just using it? See
[CONTRIBUTING.md](https://github.com/faustinolopezramos/ducta/blob/main/CONTRIBUTING.md)
for the full development setup (Poetry, Docker, tests) and workflow.

---

## License

[Apache License 2.0](LICENSE). Copyright © Faustino Lopez Ramos.
