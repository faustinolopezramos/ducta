# Ducta Console

> **The command-line interface of Ducta — the `ducta` executable.** It parses arguments, discovers and validates configuration, dispatches to the execution engine, scaffolds new projects from templates, and renders rich, developer-friendly output and error diagnostics.

## At a glance

| | |
|---|---|
| **Purpose** | Human/CI entry point: run pipelines, scaffold projects, inspect configs and quality |
| **Layer** | Interface (CLI) |
| **Depends on** | `core`, `setting`, `check` |
| **Used by** | End users & CI (the `ducta` command) |
| **Key entry points** | `ducta` console script → `UnifiedCLI`, subcommands (`start`, `stream`, `template`, `quality`, …) |
| **Install** | Bundled with the core engine (`pip install ducta`) |

## Where it fits

```mermaid
flowchart TD
    console["console · CLI"] --> core
    api["api · REST / WebSocket"] --> core
    ui["ui · Web UI"] --> api
    setting["setting · Config foundation"] --> core["core · Orchestration"]
    core --> gate["gate · Data I/O"]
    core --> stream["stream · Streaming"]
    core --> check["check · Data quality"]
    core --> mlrun["mlrun · MLOps"]
    style console fill:#4f46e5,stroke:#312e81,color:#fff
```

---

## 1. Overview

### For Non-Technical Users
Ducta Console is the **control panel you type into**. From a single `ducta` command you can start a pipeline, watch a live stream, generate a ready-to-run project, check data quality, and manage models — with clear, color-coded output that explains what happened and what to do when something goes wrong.

### For Technical Users
Ducta Console is the CLI/UX layer, implementing:
*   **Unified dispatch**: `UnifiedCLI` maps each subcommand to a `(validator, handler)` pair, restores the working directory no matter how a handler exits, and translates failures into stable `ExitCode`s (`cli.py`).
*   **Argument parsing**: a composed `UnifiedArgumentParser` builds the full subcommand tree (`parser.py`).
*   **Project discovery**: `ConfigManager` finds the project a command works on — the nearest `ducta.yaml` with `version: 2` from `--base-path` (or the cwd) upwards — runs the command from its root, and reports a missing project with how to create one (`config.py`).
*   **Validation**: field/enum/JSON/date validators for command-line arguments (`validation.py`); project files are validated by `ducta.setting.project_loader`.
*   **Execution bridge**: `load_context(path, env)` builds a project's `Context`; thin wrappers construct a `PipelineExecutor` and run batch/streaming pipelines (`execution.py`).
*   **Project scaffolding**: `template.py` generates runnable projects (`ducta.yaml`, `catalog.yaml` or `catalog/<layer>`, `quality/profiles`, `pipelines/`), verified to compile in every environment; `template_layout.py` cuts the single-file templates into the split layout without losing their comments.
*   **Rich UX**: Rich-based logging, schema formatters, and an `error_analyzer` that turns tracebacks into actionable developer guidance (`ux/`).
*   **Command groups**: execution, quality, config, MLOps (experiment/model), ingestion `init`, and run-certificate `certify` (`commands/`, `mlops_commands.py`).

---

## 2. Commands & Options

Invoked as `ducta <subcommand> [options]`:

| Subcommand | Purpose |
|------------|---------|
| `start`    | Run a batch/ML/hybrid pipeline (`--pipeline`, `--env`, `--start-date`, `--end-date`, `--node`, `--dry-run`, `--validate-only`) |
| `stream`   | `run` / `status` / `stop` a streaming pipeline (`--mode sync\|async`, `--execution-id`) |
| `init project` | Create a project in the recommended layout (`--name`, `--type batch|ml|streaming|hybrid`, `--format yaml|toml|json`, `--path`, `--layout split|single`) |
| `template` | Scaffold a new project (`--template`, `--project-name`, `--output-path`, `--evidence-level`, `--format yaml|toml|json`) |
| `config`   | `validate`, `list-pipelines`, `pipeline-info`, `schema`, `show`, `explain`, `diff`, `convert` |
| `ui` / `server` | Launch the local web UI / API server (`--host`, `--port`, `--no-browser`) |
| `quality`  | `list` / `run` / `report` / `trend` / `score` / `validate-config` for data quality |
| `experiment` | `list` / `runs` / `show` / `compare` tracked experiments (`--env`, `--pipeline`, `--storage-path`) |
| `model`    | `promote` / `gc` registered models (both read the project's `settings.mlops`; without `--env`, the base project's) |
| `init`     | `project` (above), or `ingestion setup` / `list` / `test` / `info` for database connections |
| `certify`  | `list` / `show` / `verify` / `diff` Run Certificates (`--env`, `--dir`, `--base-path`) |
| `profile`  | Assay a data file and propose the quality spec it already satisfies |
| `ai`       | Draft, fix, review and explain with a model; `architect` and `sentinel` agents |
| `skill`    | `install` / `export` / `path` the agent skill for AI assistants |

Global flags: `-V/--version`, `-v/--verbose` and `-q/--quiet` (the last two also
after `start`). `start` adds `--log-level` and `--log-file`. `-e`/`-p` are short for
`--env`/`--pipeline` everywhere. Commands that work on a project take `--base-path`
(after the subcommand; `config` also before it) and otherwise find the project
from the current directory upwards. `ducta` alone shows the project and what to
run next.

**What the terminal shows.** By default the classic log: every line as it happens
(`-v` adds debug, `-q` keeps errors only). `DUCTA_CONSOLE=compact` turns on an
optional short view (`ux/view.py`): a header, one line per node, a summary, and one
error block with the user's file and line (full error in `logs/last-error.txt`).
`ui`/`server`, the library and the API server always use the classic log.

**Logs.** A command that works on a project logs everything, at DEBUG, to
`<project>/logs/ducta.log` (`--log-file` overrides it). Outside a project, and for
`template`, `ai` and `skill`, there is no log file. Colour only on a terminal; set
`FORCE_COLOR=1` to keep it in a pipe.

**Exit codes.** `0` success · `1` unexpected error · `2` configuration ·
`3` validation (bad arguments, unknown pipeline or node, failed checks) ·
`4` execution (a run, sweep trial or connection failed) · `5` dependency (nodes
skipped for missing inputs; a connection that could not be tested) · `6` security ·
`7` locked.

---

## 3. Usage Examples

```bash
# Version / help
ducta --version
ducta --help

# Scaffold a new project, then run a pipeline
ducta template --template medallion_basic --project-name my_project
cd my_project
ducta start --env dev --pipeline sales_daily \
  --start-date 2026-01-01 --end-date 2026-01-31

# Validate configuration without executing
ducta start --env dev --pipeline sales_daily --validate-only
ducta config list-pipelines

# Streaming lifecycle
ducta stream run --pipeline events_stream --mode async
ducta stream status --execution-id <id> --format table
ducta stream stop --execution-id <id> --timeout 60

# Data quality on a file
ducta quality run --input data/sales.parquet --format parquet --config checks.yaml

# MLOps
ducta experiment list --storage-path ./mlops_data
ducta model promote sales_model 3 production --env prod

# Run certificate + local UI
ducta certify verify --run-id <run_id>
ducta ui --port 8000
```

---

## 4. Python Quickstart

The CLI is normally used from a shell, but its entry point is programmatically callable:

### Step 1: Invoke the CLI in-process
```python
from ducta.console.cli import UnifiedCLI

cli = UnifiedCLI()
exit_code = cli.run(["start", "--env", "dev", "--pipeline", "sales_daily"])
print(exit_code)   # 0 == ExitCode.SUCCESS
```

### Step 2: Reuse the execution wrappers directly
```python
from ducta.console import execution

execution.run_streaming_pipeline_cli(
    config="path/to/project",     # ducta.yaml, or any file/directory in the project
    pipeline="events_stream",
    mode="async",
    env="dev",
)
```

### Step 3: Load a project
```python
from ducta.console.execution import load_context

context = load_context("path/to/project", env="dev")   # validated; raises on problems
print(sorted(context.pipelines_config))
```

### Step 4: Generate a project template
```python
import argparse
from ducta.console import template

args = argparse.Namespace(
    template="medallion_basic", project_name="my_project", output_path="./my_project",
    list_templates=False, no_sample_code=False,
)
template.handle_template_command(args)
```
