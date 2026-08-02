# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **A web page could drive the local API.** The defaults combined
  `cors_origins=["*"]`, `cors_allow_credentials=true`, `auth_enabled=false` and
  `environment=development` — and the wildcard-with-credentials downgrade
  explicitly exempted development, which is the default. Starlette therefore
  reflected any `Origin` back with `Access-Control-Allow-Credentials: true`, so
  any site a developer visited while running `ducta ui` could call
  `/api/workspace/auto-detect` for the project path, `PUT
  /api/workspace/files/content` to write Python into it, and
  `POST /api/projects/{id}/pipelines/{name}/execute` to run it. Binding to
  loopback is no defence here: the browser is on the loopback host. The default
  is now an explicit loopback allow-list (the Vite dev/preview ports), and the
  wildcard downgrade applies in **every** environment.
- **The SQL sanitizer silently lost four of its five layers when sqlglot was
  installed.** `sqlglot.expressions.Truncate` was removed in sqlglot 30, and the
  dangerous-operation tuple was built eagerly, so one `AttributeError` skipped
  the entire AST scan behind a `logger.warning`. Because the AST path *replaced*
  the lexical path rather than complementing it, having sqlglot present was
  strictly weaker than not having it: no keyword denylist, no comment safety, no
  suspicious-pattern check, no stacked-statement check. Data-modifying CTEs
  (`WITH x AS (INSERT … RETURNING *) SELECT * FROM x`) parse with a `Select` at
  the root, so the scan was the only thing standing between them and the JDBC
  gateway — and it was dead. Lexical and structural checks now both run,
  expression classes resolve by name at call time, an unresolvable scan fails
  closed, and `sqlglot` is bounded `<31`.

### Changed

- **Relicensed from AGPL-3.0-or-later to Apache-2.0.** Made before the first
  PyPI publish, with a single copyright holder and no external contributors,
  so the change carries no compatibility obligations. The prior AGPL network
  clause applied directly to `ducta.api` (REST + WebSocket + web UI), a
  headline feature rather than an edge case, which made it a meaningful
  adoption barrier with no monetization strategy in place to justify it.
  Apache-2.0 is also the license used across this project's own dependency
  ecosystem (Spark, Airflow, Kafka, Arrow). Updated: `LICENSE`, the
  `SPDX-License-Identifier` header in all 240 source files, `pyproject.toml`
  (`license`, classifiers), and the README badge/footer.

### Added

- **Spark integration tests** (`tests/integration/`, marked `@pytest.mark.spark`).
  The suite had 1259 tests running in 3 seconds against a mocked Spark and *zero*
  tests behind the `spark` marker, so CI installed a JDK and pyspark for nothing
  and the primary execution engine was never exercised. These cover the gate
  against real DataFrames and run the README walkthrough end to end through the
  console entry point (template → list-pipelines → start → certificate verify).
  The first run of them found the `pyspark.sql.pandas` / `distutils` gap below.

### Fixed

- **The UI's file browser could never list a directory.**
  `WorkspaceManager.list_directory` called `posix_relative(self.root, item)`, but
  the helper's signature is `(path, base)` — so it computed
  `root.relative_to(entry)`. A directory entry is never a parent of the root, so
  every non-empty directory raised `ValueError`, which the route returned as a
  404. `GET /api/workspace/files` therefore failed for every real project. The
  three other call sites of the helper (in `git_utils`) already passed the
  arguments the right way round.
- **Real Spark DataFrames were unrecognised on Python 3.12 and 3.13.**
  `SparkDataFrame` and `ConnectDataFrame` were imported in a single `try/except
  ImportError`, and `pyspark.sql.connect` fails to import on 3.12+ because it
  still imports the removed `distutils` — so the fallback replaced *both* names
  with dummy classes and `isinstance(df, SparkDataFrame)` was false for every
  genuine DataFrame, on two of the four supported Python versions. Only the
  module-name fallback in `is_spark_dataframe()` kept it working by accident.
  The imports are now independent.
- **`pip install "ducta[spark]"` could not convert pandas to Spark on Python
  3.12+.** pyspark 3.5's `require_minimum_pandas_version()` imports `distutils`,
  which 3.12 removed from the stdlib and whose venvs no longer ship setuptools;
  `convert_to_spark()` raised `ModuleNotFoundError` on any pandas input. The
  `spark` extra now depends on `setuptools` (which re-provides `distutils`) for
  Python >= 3.12.
- **Every CLI pipeline run printed serialized JSON logs over its own output.**
  `ducta.api.main` created its FastAPI app at import time, and `create_app()`
  calls `configure_logging()`, which does `logger.remove()` and installs a JSON
  stdout sink — so importing anything under `ducta.api` tore down the caller's
  logging. `core/node_executor.py` imported an API helper on the node-execution
  path, so an `[api]`/`[all]` install dumped 48 JSON records onto stdout during
  `ducta start`. The app is now built lazily on attribute access (uvicorn's
  `ducta.api.main:app` still works), and the node-id ContextVars moved to
  `ducta.core.execution_context` so `core` no longer imports `api` at all.
- **Streaming was entirely non-functional.** `StreamingQueryManager` kept a stale
  copy of the trigger and checkpoint logic that had already been extracted into
  `TriggerScheduler` / `CheckpointManager`, but without its imports — 13
  undefined names on the live `create_and_start_query` path, so every streaming
  query raised `NameError`. The extraction is now completed and the manager
  delegates to both collaborators.
- **`pip install "ducta[api]"` produced an unimportable API.** `msgpack` was
  imported by `api/routes/execution.py` but declared nowhere; it is now part of
  the `api` extra.
- **`pip install "ducta[all]"` disabled local execution.** `databricks-connect`
  overwrites the `pyspark` package, leaving only remote Databricks sessions
  working. It moved to its own mutually exclusive `databricks` extra, and a
  failed local session now raises an explicit diagnostic instead of Spark's
  opaque "Only remote Spark sessions are supported".
- **`pip install "ducta[spark]"` was impossible on Python 3.13.** `pyarrow` was
  pinned `<17.0.0`, which has no cp313 wheels; the range is now `>=15,<20`.
- **`from Ducta import …` (capital D) in five modules** resolved only on
  case-insensitive filesystems, so `ducta --version` crashed on Linux and run
  certificates recorded `ducta_version: "unknown"`. Same defect in the layered
  manifest (`Ducta.yaml`), the config bundle stems, and `prog="Ducta"`.
- **Run state was split between `.Ducta/` and `.ducta/`** — one directory on
  macOS, two on Linux. Everything now uses `.ducta/`.
- **Layered projects stopped being detected when a settings file existed
  without layer definitions**, because the resolution chain used `elif` and
  never reached the manifest or auto-detection. Each step now falls through on
  an empty result.
- `sqlglot` is a declared core dependency, so AST-based SQL sanitization no
  longer degrades silently to the weaker regex fallback.

### Changed

- The layered-project settings file moved from `.claude/settings.json` (Claude
  Code's file, with a `"Ducta"` key) to `.ducta/settings.json` (key `"ducta"`).
- Certificate field `Ducta_version` renamed to `ducta_version`.
- `fastapi` is now bounded (`>=0.104.0,<1.0.0`).

### Added

- GitHub Actions CI: lint, tests on Python 3.10–3.13, a clean-install matrix
  that imports every entry point (catching undeclared dependencies), and a docs
  build.

## [0.1.0] - 2026-07-22

First public release. Ducta is a unified data-pipeline framework that runs
**batch, streaming, ML, and hybrid** pipelines from declarative configuration,
with data quality, MLOps, and run governance built in.

### Added

#### Configuration (`ducta.setting`)
- Multi-format config loading (YAML / TOML / JSON / Python) with path-traversal
  protection and clear per-format errors.
- Pydantic-validated schemas for global settings, pipelines, nodes, inputs, and
  outputs, with fail-fast validation.
- `${VAR}` interpolation with OS-environment precedence and circular-reference
  guards; environment normalization, aliases, and inheritance/fallback chains
  (`base`/`dev`/`sandbox`/`staging`/`prod`, plus `sandbox_<developer>`).
- `Context` / `ContextFactory` construction and detection of layered
  (medallion) projects.
- Thread-safe Spark session management with per-config caching and cleanup.

#### Execution engine (`ducta.core`)
- `PipelineExecutor` with specialized batch, streaming, hybrid, and ML executors.
- DAG dependency resolution (explicit ∪ dataset-inferred), cycle detection,
  topological sort, and DAG-aware parallel node execution with per-node timeouts.
- Configuration preflight that fails fast before any node runs.
- Tamper-evident **Run Certificates** (SHA-256 content hash, optional HMAC
  signing) emitted per terminating run.
- Chain-reuse of already-materialized upstream pipelines, and a security-hardened
  module importer (whitelist prefixes, path-traversal guards, bounded cache).

#### Data I/O (`ducta.gate`)
- Unified DataFrame I/O across Apache Spark, Pandas, and Polars.
- Declarative JDBC gateway with dynamic driver management.
- SQL sanitization via AST parsing (with a regex fallback) to block
  write/modify operations.
- In-memory node-to-node handoff and Unity Catalog support.

#### Streaming (`ducta.stream`)
- Spark Structured Streaming pipelines with Kafka, Kinesis, Delta, and file
  sources and multiple sinks.
- Lifecycle management with dependency-wave startup, per-query health
  monitoring, traversal-safe checkpoint paths, and push-model progress metrics.

#### Data quality (`ducta.check`)
- Engine-agnostic (Pandas/Spark) pre-execution sanity checks and
  post-execution data-quality checks.
- Quality Gates with weighted scoring and `block` / `warn` / `skip-downstream`
  behavior; reusable profiles, report persistence, and custom `@register_check`
  extensions.

#### MLOps (`ducta.mlrun`)
- Self-contained experiment tracking and versioned model registry with pluggable
  local / Databricks storage backends.
- Data/lineage fingerprinting, reproducible dataset splitting
  (random / stratified / temporal / group), hyperparameter search, and an
  optional MLflow bridge.

#### Interfaces
- `ducta` command-line interface (`ducta.console`) covering pipeline execution,
  streaming, templates, config inspection, quality, and MLOps.
- FastAPI REST + WebSocket server (`ducta.api`) with optional JWT authentication,
  SSRF-guarded Git source resolution, per-IP rate limiting, and optional
  SQLAlchemy persistence.
- React + TypeScript web workspace (`ducta.ui`) served by the API.

#### Packaging & tooling
- Lean core install with opt-in extras: `spark`, `api`, `database`, `mlops`,
  `monitoring`, and `all`.
- Cross-platform Docker image and Compose file (native `linux/amd64` and
  `linux/arm64`, including Apple Silicon).
- Unit test suites and coverage configuration.

[Unreleased]: https://github.com/faustinolopezramos/ducta/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/faustinolopezramos/ducta/releases/tag/v0.1.0
