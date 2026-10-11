# The project: `ducta.yaml`, environments, variables, formats

## Contents
- [Finding the project](#finding-the-project)
- [ducta.yaml](#ductayaml)
- [Settings most projects touch](#settings-most-projects-touch)
- [Defaults and pipeline templates](#defaults-and-pipeline-templates)
- [Environments](#environments)
- [Variables and secrets](#variables-and-secrets)
- [File formats](#file-formats)
- [Inspecting what a project resolves to](#inspecting-what-a-project-resolves-to)

The authoritative list of every key is `ducta config schema` (JSON Schema). When this
file and the schema disagree, the schema wins.

## Finding the project

Commands look from the current directory (or `--base-path`) upwards for the first
folder holding a `ducta.yaml` with `version: 2` (at its root or under `config/`).
`ducta stream …` takes `--config` instead.

## ducta.yaml

```yaml
version: 2                       # required, always 2
project: sales                   # required
description: Orders to daily revenue
paths: {input: data, output: data}   # required; base folders or URIs
settings:
  max_parallel_nodes: 4
  evidence_level: record
defaults:
  catalog:
    "bronze.*": {format: parquet}
environments:
  dev:
    settings: {max_parallel_nodes: 1, log_level: DEBUG}
  prod:
    paths: {output: s3://lake/curated}
    settings: {max_parallel_nodes: 16, evidence_level: signed}
metadata: {owner: data-team}     # free-form; Ducta never reads it
```

Top-level keys: `version`, `project`, `description`, `paths`, `settings`, `defaults`,
`environments`, `metadata`, `governance` (protected environments), `alerts`.

**Strict:** unknown keys are errors with file, line and a suggestion. Free-form data
goes under `metadata:` (allowed in `ducta.yaml`, on pipelines and on nodes).

## Settings most projects touch

| Setting | Effect (default) |
|---|---|
| `mode` | `local` (default), `databricks`, `distributed` |
| `max_parallel_nodes` | independent nodes run in parallel, up to this many (4) |
| `node_timeout_seconds` / `execution_timeout_seconds` | per-node (1800) and per-run (3600) limits |
| `evidence_level` | `off`, `record` (default), `required`, `signed` (needs `DUCTA_CERTIFICATE_KEY`) |
| `run_lock` | `{enabled, backend: local\|storage, on_conflict: fail\|wait}` — `storage` when runs start on several hosts |
| `fingerprint_mode` | `auto` (default), `exact`, `sample`, `schema` |
| `in_memory_handoff` | pass outputs to dependants in memory (false) |
| `spark_config` | Spark session settings, e.g. `{spark.sql.shuffle.partitions: 8}` |
| `log_level` | `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |
| `quality` | profiles, extensions, report output — see [quality](quality.md) |
| `ingestion` | `{sources_path: sources.yaml}` — see [ingestion](ingestion.md) |
| `mlops_enabled`, `mlops_required`, `mlops_path`, `mlflow` | see [mlops](mlops.md) |
| `strict_module_import` | only project modules may be named in `run:` (on by default; keep it) |

`input_path`/`output_path` are not settings: use `paths`.

## Defaults and pipeline templates

`defaults` in `ducta.yaml` (and, for nodes, in a pipeline file) gives datasets and nodes
the values they do not set. Precedence, lowest first: project `defaults` < pipeline
`defaults` < the dataset/node itself < the active environment's overrides.

```yaml
defaults:
  catalog:                    # {glob: dataset keys}, applied in order
    "silver.*": {format: delta}
  node: {retry: 2}            # retry, timeout_seconds, on_missing_input, fail_fast
  stream:
    streaming: {trigger: 10s, output_mode: append}
```

A **pipeline template** is a pipeline written once under `templates/` with
`${params.name}` placeholders:

```yaml
# pipelines/bronze.customers.yaml
extends: templates/ingest_csv
params: {table: customers, source: data/raw/customers.csv}
```

The template declares its `params` (`null` = required). Mappings merge, lists and
scalars replace. A placeholder may be part of a key (to give each copy unique node
names); in YAML write such templates in block style. A template cannot extend another.

## Environments

Known names: `base` (the default when `--env` is omitted), `dev`, `sandbox`,
`sandbox_<developer>`, `staging`, `prod`; any other name works too.

`environments.<env>` holds **only what differs** and is deep-merged over the whole
project:

```yaml
environments:
  prod:
    paths: {input: s3://lake/raw, output: s3://lake/curated}
    settings: {run_lock: {backend: storage}}
    catalog.gold.sales.daily.write.mode: append                   # dotted key: one value
    pipelines.etl.nodes.clean.quality.gate.on_fail: stop_all
```

- Mappings merge key by key; lists and scalars replace.
- An override may address only `settings`, `paths`, `catalog`, `pipelines`, `metadata`.
- A dotted key must name something that exists (a typo is an error at `ducta.yaml`).
- `sandbox_alice` uses its own block, else `sandbox`'s. No other inheritance:
  `staging` does not pick up `prod`.
- An environment with no block runs the base project.

Validate each environment: `ducta config validate --env prod` (without `--env`: base).

## Variables and secrets

Inside the catalog and settings:

- `${paths.input}`, `${paths.output}` — the environment's paths;
- `${env}` — the active environment name;
- `${NAME}` — the process environment variable `NAME` (also from `.env`). An unset
  variable is left as written.

`${NAME}` **refuses names that look like secrets** (containing `PASSWORD`, `SECRET`,
`TOKEN`, `KEY`, `CREDENTIAL`). Credentials go elsewhere:

- database sources read `<SOURCE>_USER` / `<SOURCE>_PASSWORD` from the environment or
  `.env` — see [ingestion](ingestion.md);
- cloud storage uses the platform's credentials (instance profiles, `AWS_*`, Databricks);
- the certificate signing key is `DUCTA_CERTIFICATE_KEY`.

Keep `.env` out of version control.

## File formats

Every file can be YAML, TOML or JSON (`ducta.yaml|toml|json`, same for the catalog,
pipelines and templates). One file per role: `ducta.yaml` next to `ducta.toml` is an
error. Formats can be mixed per file, but keep one per project.

- YAML: comments survive; quote values like `no`, `on`, `1e3`.
- TOML: no null (write a required template param as `"<required>"`); dotted names are
  quoted keys: `[defaults.catalog."bronze.*"]`.
- JSON: no comments; a top-level `"$schema"` is ignored.

`ducta config convert --to toml --out ../proj-toml` rewrites a whole project (no
comments; Python and data are not copied).

Editor completion: `ducta config schema --out .` writes `.ducta/schema/*.json`; YAML
files reference it with `# yaml-language-server: $schema=.ducta/schema/project.json`.

## Inspecting what a project resolves to

```bash
ducta config validate --env prod --output-format json   # every problem, located
ducta config show --env prod                            # after templates, defaults, overrides
ducta config show --pipeline etl --format json          # one pipeline and its datasets
ducta config show --engine --format json                # the five documents the engine reads
ducta config explain settings.max_parallel_nodes --env prod   # where a value comes from
ducta config diff dev prod                              # every value that differs
ducta config list-pipelines --output-format json
```
