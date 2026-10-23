---
name: ducta
description: Install, configure, run and troubleshoot Ducta, the configuration-as-code data-pipeline framework (batch, streaming, ML and hybrid pipelines on Spark or pandas). Use when the project has a ducta.yaml, catalog.yaml or catalog/, or pipelines/*.yaml, when the user mentions Ducta or the ducta CLI, or wants to create or fix medallion (bronze/silver/gold) pipelines, catalog datasets, ingestion sources, data quality checks and gates, MLOps training and model serving, streaming jobs, run certificates, or the Ducta web UI and server.
license: Apache-2.0
compatibility: Requires the ducta CLI (pip install ducta; Python 3.10-3.13). Works with any agent that can read files and run shell commands.
metadata:
  ducta-version: "0.2"
  skill-version: "1.1.1"
  homepage: https://github.com/faustinolopezramos/ducta
---

# Ducta

Ducta runs data pipelines described in files: **what** runs is YAML (or TOML/JSON),
**how** is plain Python functions. A project is:

```text
my_project/
├── ducta.yaml          # version: 2, project, paths, settings, defaults, environments
├── catalog.yaml        # every dataset once (or catalog/<layer>.yaml)
├── pipelines/
│   ├── etl.yaml        # one pipeline per file; the file name is the pipeline name
│   └── etl.py          # the functions its nodes run
└── .ducta/schema/      # generated JSON Schemas for editors
```

Answer in the user's language. Prefer showing the exact command or the minimal file
edit over long explanations.

## First steps, every time

1. Check the environment (read-only, prints JSON). `scripts/` is inside this
   skill's folder (e.g. `.claude/skills/ducta/` or `.agents/skills/ducta/`); run it
   from the project folder:

   ```bash
   python3 <this skill's folder>/scripts/check_env.py --project .
   ```

   It reports Python, the installed Ducta version, which extras are installed,
   Java, the project root, and `warnings`. Act on the warnings first.
2. If `ducta.version` does not start with `metadata.ducta-version` above, tell the
   user, and trust `ducta <command> --help` and `ducta config schema` over these
   references.
3. Find the project root: the nearest folder upwards holding `ducta.yaml`
   (`project_root` in the output). Run commands from there.
4. Get the project's state before changing anything:

   ```bash
   ducta config validate --env dev --output-format json
   ```

   Exit code 0: valid. 2: the project does not load (`config_error`). 3: it loads
   but preflight found problems (`pipelines.<name>.problems`).

## Golden rules

- **Look, do not guess.** The format is whatever `ducta config schema` prints; the
  state is whatever `ducta config validate --output-format json` says; a resolved
  value is whatever `ducta config explain <path> --env <env>` says.
- **Smallest change, then validate again.** Fix one problem at a time and re-run
  validation until it is clean.
- **Ask before writing files**, and show the change you propose.
- **Never, unless the user explicitly asks:** commit or push; run in a protected
  environment (`prod`, `production`); delete data, checkpoints or model versions;
  pass `--force`.
- **Credentials never go in project files.** Use environment variables or `.env`
  (kept out of git). Never print a secret's value, and never ask the user to paste
  one into the chat.
- **Validation runs project code.** `ducta config validate` and
  `ducta start --validate-only` import the project's Python modules. Say so
  before running them on code you have not read.
- **Unknown keys are errors.** Ducta is strict: a typo is reported with file, line
  and a "did you mean". Never invent keys; check the schema.

## Task map — which reference to open

| The user wants to… | Read |
|---|---|
| install Ducta, extras, Java/Spark, Windows | [installation](references/installation.md) |
| understand or edit `ducta.yaml`, environments, variables, file formats | [project-format](references/project-format.md) |
| add or change a pipeline or node | [pipelines](references/pipelines.md) |
| declare datasets, formats, paths, write modes | [catalog](references/catalog.md) |
| read from a database (`kind: ingest`, `sources.yaml`) | [ingestion](references/ingestion.md) |
| run pipelines, dates, environments, certificates, exit codes | [execution](references/execution.md) |
| data quality checks, contracts, gates, profiles | [quality](references/quality.md) |
| ML pipelines, split, hyperparameters, registry, serving | [mlops](references/mlops.md) |
| Structured Streaming pipelines | [streaming](references/streaming.md) |
| the web UI, the API server, auth and permissions | [server-and-ui](references/server-and-ui.md) |
| run on Databricks / Unity Catalog | [databricks](references/databricks.md) |
| draft, fix, extend (add nodes) or review pipelines with `ducta ai` | [ai-builder](references/ai-builder.md) |
| design several pipelines, or handle failed/late runs (Architect, Sentinel) | [agents](references/agents.md) |
| conventions, testing, production readiness | [best-practices](references/best-practices.md) |
| an error message or something that does not work | [troubleshooting](references/troubleshooting.md) |
| the exact options of any command | [cli](references/cli.md) |

`assets/examples/sales/` is a small, valid project (ingest node, transforms, contract,
profile, environments) to copy patterns from.

## Core workflows

### Install

1. Run `scripts/check_env.py`. If `ducta.command` is null, Ducta is not installed in
   the active environment.
2. Recommend a virtual environment, then `pip install "ducta[spark]"` for local Spark
   pipelines; add extras by need (`api` for the UI, `mlops`, `ai`, `delta`,
   `databricks`). See [installation](references/installation.md).
3. Check again with `scripts/check_env.py` and `ducta --version`.

### Create a project

1. Pick a starting point: `ducta template --list-templates` (runnable examples:
   `medallion_basic`, `streaming_basic`, `ml_basic`, `ml_scoring`, `hybrid_basic`)
   or `ducta init project --name NAME --type batch|ml|streaming|hybrid` (the layout a
   larger project grows into).
2. `cd` into it and run `ducta config validate --env dev --output-format json`.
3. Run the sample: `ducta start --env dev --pipeline etl` (template) and show the user
   what was written.

### Add a pipeline or a node

1. Read the existing pipelines and the catalog to reuse datasets and follow naming
   (`layer.domain.table` datasets, `layer.domain` pipelines).
2. Write the node in `pipelines/<name>.yaml`: `run: module:function`,
   `inputs: {param: dataset}`, `outputs: [dataset]`.
3. Declare every new dataset once in the catalog.
4. Write the function: one parameter per `inputs` key (same names), returns one
   DataFrame. Pure: no reads or writes of its own.
5. Validate; fix; repeat. See [pipelines](references/pipelines.md).

### Validate and fix (the loop)

1. `ducta config validate --env <env> --output-format json`.
2. For each problem: open `file` at `line`. When `fix` is present, `fix.label` says
   what it does and `fix.replace` is `[old, new]` text to swap at that line; otherwise
   read the matching reference.
3. Validate again. Then validate every environment the project declares
   (`environments:` in `ducta.yaml`) — an override can break one environment only.

### Run in dev

1. `ducta list` to see what can run.
2. Pipelines default to `requires_dates: true`:
   `ducta start --env dev --pipeline NAME --start-date YYYY-MM-DD --end-date YYYY-MM-DD`.
3. `--validate-only`, `--dry-run` and `--node NAME` narrow a first run.
4. Read the exit code (0 ok, 2 configuration, 3 arguments, 4 the run failed,
   5 nodes skipped for a missing input, 7 locked — retry later). See [execution](references/execution.md).

### Diagnose a failed run

1. Re-run the failing node alone with `-n NAME -v`, or read `logs/ducta.log` (every
   line, at debug level). With `DUCTA_CONSOLE=compact` a failure ends with one block —
   the error, the file and line of the user's code, the command to re-run the node —
   and the full traceback goes to `logs/last-error.txt`.
2. Match the error in [troubleshooting](references/troubleshooting.md) (Java/Arrow,
   missing extra, import errors, dates, locks, quality gates).
3. `ducta certify list --env dev` and `ducta certify show --run-id ID` show what ran,
   on which data and with which quality outcome.
4. With an AI model configured, `ducta ai fix PIPELINE --error-file run.log` drafts a
   fix for review.

### Data quality

Put a contract (`quality`) on catalog datasets you do not control, checks plus a
`gate` on node outputs others depend on. `ducta profile --input FILE` proposes checks
from real data; `ducta quality validate-config --node NAME --env ENV` checks a node's
quality block without data. See [quality](references/quality.md).

### MLOps, streaming, UI, Databricks, AI builder

Open the matching reference from the task map; each starts with the minimal working
setup and the commands to check it.

## Reading `config validate --output-format json`

```json
{"ok": false, "env": "dev",
 "pipelines": {},
 "config_error": [
   {"severity": "error", "code": "unknown_key", "source": "config",
    "message": "...unknown key 'outptus' — did you mean 'outputs'?",
    "file": "pipelines/etl.yaml", "line": 21, "node": null, "pipeline": null,
    "fix": {"label": "Replace 'outptus' with 'outputs'", "replace": ["outptus", "outputs"]}}]}
```

When the project loads, problems found by preflight (a function that is not found,
a parameter that does not match its `inputs` key…) appear per pipeline instead:
`"pipelines": {"etl": {"ok": false, "problems": [...]}}`, with `source: "preflight"`.

- `config_error` non-empty: the project does not load at all — fix these first.
- `fix.replace: [old, new]`: replace `old` with `new` at `file`:`line`; still read the
  line first.
- `severity: warning` never fails a run; mention it, do not block on it.
- `code` classifies it (`unknown_key`, `unknown_dataset`, `function_not_found`,
  `cycle`, `missing_field`, `duplicate_definition`, …; `config` when unclassified).
- `file`/`line` may be missing for problems found in Python code; then `node` names
  the node whose function is wrong.

## When stuck

1. Search [troubleshooting](references/troubleshooting.md) for the error text.
2. Read `ducta <command> --help` and `ducta config schema` for the installed version.
3. If it is still unclear, tell the user what you checked, what you know, and what
   you would need (a log, the failing file, the Ducta version) — do not guess.
