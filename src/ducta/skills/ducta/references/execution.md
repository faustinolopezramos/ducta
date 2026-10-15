# Running pipelines

## The basic run

```bash
ducta config list-pipelines                       # what can run
ducta start --env dev --pipeline etl --start-date 2026-01-01 --end-date 2026-01-31
```

- `--pipeline` is the file name under `pipelines/` (without extension).
- `--env` defaults to `base` (the project as written, no overrides). Use `dev` for
  development; never `prod` unless the user asks.
- Pipelines default to `requires_dates: true` → `--start-date` and `--end-date`
  (`YYYY-MM-DD`) are required. Datasets with `incremental:` read only that window.
  Pipelines with `requires_dates: false` take no dates.

## Narrowing a run

| Option | Does |
|---|---|
| `--validate-only` | configuration + preflight (modules import, functions exist, inputs match parameters, paths resolve) — runs nothing |
| `--dry-run` | logs what would run |
| `--sanity-only` | runs the input checks of every node, not the nodes |
| `--node NAME` | one node only (its inputs must already exist) |
| `--verbose` / `--log-level DEBUG` | more log |
| `--reuse-upstream` / `--rerun-all` | in a `depends_on` chain: skip still-valid upstreams / force all |
| `--mode sync` | streaming/hybrid: wait for the queries instead of returning |

ML options (`--model-version`, `--hyperparams`, `--sweep`, `--search`…) are in
[mlops](mlops.md); every option is in [cli](cli.md).

## Exit codes (`ducta start`)

| Code | Meaning | What to do |
|---|---|---|
| 0 | success | |
| 1 | unexpected error | read the log; [troubleshooting](troubleshooting.md) |
| 2 | the project cannot run as configured (no project, invalid configuration, failed preflight) | `ducta config validate --env ENV --output-format json` |
| 3 | invalid arguments (unknown pipeline, malformed date) | check `ducta config list-pipelines`, the date format |
| 4 | the pipeline ran and failed: a node raised, or a quality gate blocked one | find the failed node or gate in the log; re-run it with `--node` |
| 5 | nodes were skipped: a dataset they read is missing (an upstream that has not run) | run the upstream first, or `--reuse-upstream`; `ducta config list-pipelines` |
| 6 | a security check refused a path or module | keep `run:` inside the project's own modules |
| 7 | **locked**: another run is writing one of its outputs; nothing ran | wait and retry; see `settings.run_lock` |

`ducta config validate` exits 0 (valid), 2 (does not load) or 3 (preflight problems).

## What a run does

1. Validates every file and reference (fails fast with file and line).
2. Applies the environment's overrides and reads `.env`.
3. Orders nodes from the data; independent nodes run in parallel
   (`max_parallel_nodes`).
4. Runs input checks (contracts), the node, then its output checks and gate.
5. Writes a **Run Certificate**: configuration fingerprint, input/output fingerprints,
   quality outcomes, models used.

Gate outcomes: by default a failing gate **skips the node's dependants** and the run
does not fail (`on_fail: skip_downstream`); `stop_all` fails the run; `warn_only` logs.
A run that "succeeded" may therefore have skipped nodes — read the summary.

## Run Certificates

Stored at `<paths.output>/<env>/.ducta/runs/<run_id>/certificate.json`.

```bash
ducta certify list --env dev
ducta certify show --run-id 3f9a            # a unique prefix is enough; --json for raw
ducta certify verify --run-id 3f9a          # tamper check (and signature if signed)
ducta certify verify --run-id 3f9a --reproduce --start-date 2026-01-01 --end-date 2026-01-31
ducta certify diff RUN_A RUN_B              # what changed: config, outputs, quality, models
```

`settings.evidence_level`: `off`, `record` (default), `required` (a run without its
certificate fails), `signed` (HMAC; needs `DUCTA_CERTIFICATE_KEY` in the environment).

## Scheduling

Ducta has no scheduler of its own in the CLI: call `ducta start` from cron, Airflow,
Prefect, a CI job — or use schedules in the web server (see
[server-and-ui](server-and-ui.md)). Process windows, not everything:

```bash
ducta start --env prod --pipeline daily \
  --start-date "$(date -d yesterday +%F)" --end-date "$(date -d yesterday +%F)"
```

Make writes idempotent (`merge`, `replaceWhere`) so re-running a window is safe, alert
on non-zero exit codes, and retry on 7.

## Protected environments

`governance.protected_environments` in `ducta.yaml` (default `[prod, production]`)
marks environments that, through the web server, only users with
`pipeline.execute.protected` may run. From the CLI, treat them as off-limits unless the
user explicitly asks.
