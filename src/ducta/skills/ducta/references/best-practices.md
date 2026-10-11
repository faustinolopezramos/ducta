# Conventions and production readiness

## Naming

| What | Convention | Example |
|---|---|---|
| dataset | `layer.domain.table`; layers `seed`, `bronze`, `silver`, `gold`, `ml` | `silver.sales.orders` |
| pipeline | `layer.domain` — the file name | `pipelines/silver.sales.yaml` |
| node | `verb_object`, snake_case, unique in the project | `clean_orders` |
| `inputs` keys | the function's parameter names | `inputs: {orders: bronze.sales.orders}` |
| environments | `dev`, `sandbox`, `staging`, `prod`; `sandbox_<name>` per developer | |

## Layout a project grows into

```text
my_project/
├── ducta.yaml              # aim for < 40 lines
├── catalog/                # sources.yaml, bronze.yaml, silver.yaml, gold.yaml
├── quality/profiles.yaml
├── pipelines/              # <layer>.<domain>.yaml (+ their Python, or src/)
├── templates/              # pipelines written once, used with extends/params
├── tests/
├── .ducta/schema/          # commit it: editor completion
└── .env                    # never commit
```

`ducta init project --name NAME` writes it. Keep `data/`, `logs/`, `.env` and
`.ducta/runs` out of git.

## Datasets

- Declare each dataset once; name it `layer.domain.table` so it needs no `path`.
- Contracts (`quality`) on data you do not control.
- `incremental: {column: …}` on large inputs.
- Idempotent writes: `merge` with `keys`, or `replaceWhere`; avoid plain `append` for
  windowed pipelines.

## Nodes

- Plain functions, named parameters mapped with `inputs: {param: dataset}`.
- One job per node; raise with a clear message; never swallow errors.
- No I/O inside node functions: Ducta reads and writes the datasets.
- Unit-test functions with small DataFrames.

## Environments

Override only what differs (paths, parallelism, strictness). `staging` does not inherit
from `prod`. Validate every environment in CI.

## CI

```bash
ducta config validate --env dev --output-format json
ducta config validate --env prod --output-format json
ducta start --env dev --pipeline NAME --validate-only
pytest
```

## Before the first production run

- `ducta config validate --env prod` passes in CI; node functions have tests.
- Inputs you do not own have contracts; shared outputs have gates.
- Large inputs are incremental; outputs re-runnable (`merge` / `replaceWhere`).
- `settings.run_lock` fits where runs start (`storage` for several hosts); time limits set
  (`node_timeout_seconds`, `run_in_process` for pure-Python nodes); `retry` only on
  transient failures.
- `evidence_level: required` or `signed` in prod.
- No credentials in the repository; `.env` ignored; `strict_module_import` left on.
- The scheduler alerts on non-zero exit codes and retries on 7 (locked).
- The web server, if exposed, follows the checklist in [server-and-ui](server-and-ui.md).
