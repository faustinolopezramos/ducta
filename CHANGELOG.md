# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Ducta is **alpha**: APIs and configuration can still change between minor versions.
This file keeps what you need to upgrade (breaking changes, removals, security) and the
headline of everything else; `git log` has the detail.

## [Unreleased]

## [0.3.0] - 2026-11-16

AI-assisted pipelines, a live stream monitor, ML retraining and the web server as its own
package. **Breaking changes: read the first section before upgrading from 0.2.0.**

### Changed (breaking)

- **Two packages**: `ducta` (engine + CLI) and `ducta-server` (API + web app).
  `ducta[api]`/`ducta[database]` → `pip install ducta-server`; `ducta.api` → `ducta_server`;
  Docker targets `cli` and `server`.
- **Python 3.11–3.14, Spark 3.5 or 4.2.** Python 3.10 dropped; Python 3.14 needs Spark 4.
- **Pre-0.3 compatibility removed**: old storage locations, `Ducta_*` variables (use `DUCTA_*`),
  `--format`, gate `block`/`warn` aliases, `fingerprint_mode: fast|full`.
- **Safer writes**: overwrite keeps the Delta schema (`write.overwrite_schema`), 0 rows fails the
  node (`write.allow_empty`), two datasets on one path are an error.
- **Quality fails loudly**: config/engine errors fail the node; NULL counts as a rule violation.
- **Different results**: `--end-date` includes its whole day; CSV reads with `multiLine: true`;
  `delta_stream` reads appends unless `readChangeFeed: true`.
- **ML**: a failed registration fails the node; search scores are `val_<metric>`; one experiment
  per pipeline; `certify verify --reproduce` no longer touches real data or the registry.
- **New exit codes**: `3` failed quality check, `4` failed trial or `--node`, `5` untested
  connection, `143` interrupted run.
- **Server outside localhost** needs `AUTH_ENABLED=true`, a real `JWT_SECRET_KEY` and admin password.
- **Removed**: `ui --enable-terminal`, the `runtime` Docker target, unused internal classes.

### Security

- Runs execute in their own process without the server's secrets; login throttling;
  `ducta-server user` manages accounts.
- Host/Origin checks, strict CSP; `.env` and `.git/` never served.
- TLS verified by default for SQL Server and remote PostgreSQL/MySQL/MariaDB.
- Secrets masked in logs, run evidence and AI prompts.

### Added

- **`ducta ai`**: draft, fix, review, explain and document pipelines with a local or hosted model;
  Architect and Sentinel agents; `ducta skill install`.
- **Streaming**: Delta merge, quarantine, per-batch quality, stream alerts, `ducta stream plan`,
  and a live monitor page in the web app with the rows each node writes.
- **Streams restart failed nodes**: a query that fails while running is started again with a
  doubling backoff (`streaming_restart_max_attempts`, default 3; `streaming_restart_backoff_seconds`,
  default 10), then failed for good; the node reads `restarting` meanwhile.
- **Stream state in the status and journal**: watermark, rows/bytes in state, late rows dropped,
  source lag and the sources Spark reads (a join in the transform shows both). Joins documented.
- **ML**: retrain on drift, promotion policy, `ducta model list | show`, model registry page.
- **CLI**: `ducta list`, `ducta check` (also warns about bad version combinations).
- **Loads**: dynamic partition overwrite and incremental ingestion.
- A table of all runs linked to their certificates; CLI runs appear in the web app.

### Fixed

- Ctrl+C, SIGTERM and cancel no longer record a run as successful.
- Streams: no duplicate batches on retry, hybrid runs certify their stream phase.
- Streams: an output mode or `continuous` trigger the sink cannot take is an error in
  `ducta stream plan`, not at start; `streaming_health_interval_seconds: 0` turns the check off.
- Cloud paths (`s3a://`, `abfs://`…) are no longer created as local folders.
- A project whose connections are not in `config/sources.yaml` (`settings.ingestion.sources_path`)
  no longer fails its first run with `ClassNotFoundException` for the JDBC driver: the driver
  is downloaded before the Spark session starts.
- A refused or reset connection is `infra`, not `data`, in failure diagnosis: the Java stack
  trace no longer decides the kind ("getSchema" made it a data failure), so Sentinel retries it.
- `ducta stream plan` on a `type: hybrid` pipeline plans its stream nodes and lists the batch
  phase, instead of reporting each batch node as a stream with no input format.
- A stream's file sink (Delta, Parquet, JSON, CSV, ORC) is in the run certificate's `outputs`
  (`stream.<node>`); one that cannot be read back is an evidence gap, not a silent omission.
- Many fixes in quality checks, ML tracking and the web app.

### Dependencies

- Accepts `rich` 15, `bcrypt` 5, `redis` 8, `optuna` 5, `anthropic` 2, `pyarrow` 26.
  `pandas` stays below 3.

## [0.2.0] - 2026-10-10

Configuration format 2 (`ducta.yaml`, the catalog and `pipelines/`) replaces format 1, which
is no longer read. `ducta template` writes the new format.

### Security

- No known vulnerabilities in the installed dependencies (`mlflow`, `pyarrow`, `pytest`);
  `python-jose` replaced with `PyJWT`.
- API permissions tightened (deep preflight, Git sources, model promotion and deletion).
- **Run certificates measured far less than they claimed on Spark.** Fingerprints are now
  engine-native and detect a changed, duplicated or deleted row. **Every fingerprint value
  changes.**

### Changed (breaking)

- `-e` is `--env` on every command (`stream status`/`stream stop` use `-i` for the execution).
- Saving from the web app or the API no longer commits.
- Quality reports go to `<paths.output>/<env>/quality/` instead of `.quality/`.
- A declared train/test split is enforced; MLflow 3.15 or later is required.
- A dataset's contract is `quality:`, not `checks:`.

### Removed

- Loading configuration format 1 (`ducta config migrate` converts a 0.1.x project), the
  legacy certificate switches (use `evidence_level`), and the specialized context hierarchy.

### Added

- **Configuration format 2**: 3 files instead of 15 for the medallion scaffold, unknown keys
  are errors with file and line, plus TOML/JSON projects, `defaults`, templates, quality
  profiles and `ducta config show | explain | diff | convert`.
- **Data safety and evidence**: one writer per output (run lock), Delta `merge`, `incremental`
  inputs, `evidence_level`, faster fingerprints, `on_missing_input`.
- **ML and serving**: scoring with a registered model, `train_with_search`, Spark ML models
  in the registry, `ducta experiment runs | show | compare`.
- **Web app**: an editor-like layout, an `operator` role, live streaming status.

### Changed

- Timeouts now stop the work (a timed-out node's Spark jobs are cancelled, its writes refused).

### Fixed

- Quality gates and misspelled columns, runs recorded as success when they were not,
  hybrid/streaming reporting, config validation false all-clears, and MLflow model logging.

## [0.1.1] - 2026-08-29

Security fixes for users of `0.1.0`. Not a pure patch release.

### Security

- A web page could drive the local API (CORS) and open a shell (WebSocket `Origin`); both fixed.
- The SQL sanitizer lost most of its layers when `sqlglot` was installed; ingestion no longer
  builds SQL by concatenation; an empty `GIT_CLONE_ALLOWED_HOSTS` no longer means "anywhere".

### Changed

- The CLI exits with meaningful status codes (it always exited 0), a blocked quality gate no
  longer reports success, and the license is now Apache-2.0.

### Fixed

- Run status, streaming, `config validate --env`, and the install extras `ducta[api]`,
  `ducta[all]` and `ducta[spark]`.

## [0.1.0] - 2026-07-22

First public release: batch, streaming, ML and hybrid pipelines from declarative
configuration, with data quality, MLOps, run certificates, a CLI, a REST + WebSocket server
and a web workspace.

[Unreleased]: https://github.com/faustinolopezramos/ducta/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/faustinolopezramos/ducta/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/faustinolopezramos/ducta/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/faustinolopezramos/ducta/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/faustinolopezramos/ducta/releases/tag/v0.1.0
