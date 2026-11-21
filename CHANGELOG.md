# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Ducta is **alpha**: APIs and configuration can still change between minor versions.
This file keeps what you need to upgrade (breaking changes, removals, security) and the
headline of everything else; `git log` has the detail.

## [Unreleased]

## [0.3.1] - 2026-11-21

Security fixes for the API server (most of them affect 0.3.0 servers others can reach),
and fixes. Upgrade notes: roles lose what the new permissions now guard (`data.read.protected`,
`data.read.pii`, `model.promote.production`); a server with accounts in SQLite that others can
reach refuses to start unless `ALLOW_SQLITE_WITH_ACCOUNTS=true`; certificates are schema `1.11`.

### Security

- **High: a protected environment spelt otherwise passed every guard.** The configuration
  reads `PROD` and `Production` as `prod` (lower case, aliases) and applied the `prod`
  block, but the server compared names as typed: a developer could run with prod's
  settings, read prod's rows (on macOS and Windows the same folder), schedule there,
  and Sentinel could act there. Every guard now compares names as the configuration
  reads them (`ducta.project_store.governance.is_protected`).
- **Routes that bypassed the data guards.** `POST /api/quality/run` read any workspace
  file — prod's included, PII columns included — with no permission check; it now takes
  `data.read.protected` for a protected environment's files and refuses a check naming a
  `metadata.pii` column without `data.read.pii`. A snapshot test (`POST
  .../nodes/{node}/tests/snapshot`) copied a protected environment's rows into
  `tests/fixtures`, where every role reads them: it now takes `data.read.protected`, and
  fixtures write `metadata.pii` columns as stand-ins of the same kind (an email stays an
  email — `email_1@example.invalid` —, a number a number, a date a date; the same value,
  the same stand-in; listed in the response's `masked`) for everyone, the CLI included,
  so the generated test still runs. Deleting a protected environment's quality reports
  (`DELETE /api/quality/reports/...?env=prod`) takes `pipeline.execute.protected`
  (operator, admin): a developer could erase prod's evidence.
- **AI `quality` and `docs` proposals measuring a protected environment** take
  `data.read.protected`, and no longer send a `metadata.pii` column's minimum and maximum
  to the model (nor accept a `range` proposed on one).
- **Reads of sensitive data are audited** (auth on). A request that read a protected
  environment's rows or files, a protected run's logs, errors or diagnosis, or PII
  columns unmasked, is written to `.ducta/audit.log` with `data_reads`, GETs included
  (before, only writes were). A run's logs stay visible to whoever sees the run:
  debugging prod is the job.
- **Critical: code execution in the API server from any signed-in account.**
  `POST /api/projects/{id}/quality/failing-rows` (`quality.read`, so a `viewer`) and
  `POST .../quality/try` (`quality.run`) evaluated SQL rules with sqlglot's executor,
  which turns SQL into Python and `eval`s it. A JSON path in a rule reached that code
  unescaped, so a request could run code in the server process: read `JWT_SECRET_KEY`
  and sign itself an admin token. Affects `0.2.0` and later. Rules are now interpreted
  on the sampled rows by `ducta_server.services.sql_rules` (a short list of operations,
  no code built from the rule). A rule that uses anything else is "not tried here" and
  still runs on Spark.
- **The server signs Run Certificates; the key never reaches a run.** With
  `RUN_ISOLATION=process`, a run's environment no longer carries `DUCTA_CERTIFICATE_KEY`.
  The run writes its certificate unsigned, and the server signs it when the run's process
  ends, only for the run it started and only if the certificate is unaltered. Before,
  a pipeline's code could sign a certificate for a run that never happened. The AI
  model's keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DUCTA_AI_*`, the configured
  `api_key_env`) are withheld from runs and node tests too. Debug runs get the same
  environment as any run (they got the server's whole environment).
- **Whole-commit git diffs leave secret files out.** `GET /api/git/diff/{sha}` and
  `/diff/{a}/{b}` without a path showed a `.env` that had been committed. They now
  leave out every file the file API refuses to read.
- **More files count as secret.** Private keys and keystores (`*.pem`, `*.key`,
  `*.p12`, `*.pfx`, `*.jks`, `*.keystore`), `.pgpass`, `.netrc`, `.npmrc`, `.pypirc`,
  `credentials.json`, `id_rsa`/`id_ed25519` and the like are hidden, unreadable and
  unwritable through the API, like `.env`.
- **Rows of protected environments and personal data.** The routes that return a
  dataset's rows (preview, failing rows, stream rows, trying checks) now refuse rows of a
  protected environment (`prod` by default) without the new `data.read.protected`
  permission (operator, admin). **Developers no longer see prod rows**, just as they
  cannot run there. Columns listed in `metadata.pii` read `••••` without the new
  `data.read.pii` permission (developer, admin). A check or rule naming such a column is
  refused for those roles (`403`).
- **Run logs on the server are redacted** like the CLI's log file (`password=***`,
  `Bearer ***`, credentials in URLs). Viewers read run logs.
- **Accounts in SQLite on a reachable server: refused.** Runs, node tests and preflight
  execute as the server's OS user and could open the SQLite file; a developer's
  pipeline rewrote its own role to `admin`. With `AUTH_ENABLED` on a server others can
  reach (production, or a non-loopback bind) the server now refuses to start with a
  SQLite `DATABASE_URL`. Use PostgreSQL (`docker compose --profile accounts`), or set
  `ALLOW_SQLITE_WITH_ACCOUNTS=true` if every developer is trusted as admin. On
  loopback it warns.
- **Protected environments have a floor the projects cannot lower.**
  `DUCTA_PROTECTED_ENVIRONMENTS` (default `prod,production`), set where the server
  runs, is always protected; a project's `governance.protected_environments` adds to
  it. Before, a developer could write `protected_environments: []` in `ducta.yaml` and
  run in prod. Sentinel follows the same list.
- **Data files of protected environments through the file API and git.** Reading a file
  a protected environment's runs read or write (`<output>/<env>/` and every catalog
  path) takes `data.read.protected`; changing or deleting it takes the new
  `data.write.protected` (admin only). Whole-commit diffs leave such files out for
  those without the permission. Before, the preview answered `403` while
  `GET /api/workspace/files/content` returned the same prod CSV, and a developer could
  rewrite a prod dataset or its quality history. **Viewers and developers no longer
  read those files**, including source files that prod reads.
- **Promoting to Production takes `model.promote.production`** (admin). So does
  taking the Production version out of Production or forcing past the promotion
  policy (which the project's own files define). Staging and Archived stay with
  `model.promote`.
- **PII guard in any script.** A rule naming a `metadata.pii` column written with
  accents (`teléfono`) or spaces (`` `fecha nacimiento` ``) was not recognised, and
  its count of failing rows gave the values away. Names are now matched as words in
  any script, quoted identifiers and whole values.
- **`LIKE` in rules tried on the server runs in linear time.** It was a backtracking
  regular expression: eight `%` against a 60-character value took 21 seconds, and a
  viewer could send it.
- **The editor's language server no longer gets the server's secrets**
  (`JWT_SECRET_KEY`, `DATABASE_URL`, the certificate key): it gets a run's environment.
- `SECURITY.md`: supported versions (`0.3.x`), the new in-scope items, the
  certificate-key and `metadata.pii` checklist entries. The claim that `.py` config
  files execute on load is gone; that loader no longer exists.
- `docs/adr/0001-project-access-and-certificate-signing.md` (proposed): per-project
  roles and Ed25519 signatures, the two limits left by design.

### Added

- **Governance warnings that catch what protects nothing.** `governance.pii_unknown_column`
  (a `metadata.pii` column the dataset's `schema` or contract does not state: a typo that
  masks nothing), `governance.pii_downstream` (a dataset built from personal data that
  lists no `pii` of its own; `pii: []` says it keeps none), and `missing_owner` now also
  for outputs no pipeline in the project reads (they leave it). Switched by
  `governance.warnings.pii` / `missing_owner`. `ducta check` sums the advice up in one
  line per kind (a misspelt `pii` column on its own line) and its JSON lists each under
  `governance`; they never change the exit code.
- **Run Certificates say who started the run** (schema `1.11`): `started_by` is
  `{"via": "server", "user_id": ...}` or `{"via": "cli", "user": <OS login>}`, sealed by
  the hash and signature with the rest.

### Changed

- Generated projects write quality checks under `checks:` (the form the docs teach); the README taught
  both. Listing checks directly next to `gate` still works. "Next steps" and the generated READMEs
  name `ducta check`, the command `--help` lists under Essentials, instead of `ducta config validate`.

### Fixed

- **`null_rate` failed on a dataset with no rows** ("Cannot calculate null rate"), while
  `range` and `duplicates` passed: an intent whose output may legitimately be empty could
  never be proved, nor run. With no rows it now passes; requiring rows is `empty_dataset`
  or `row_count`.
- `requirements.txt` of a generated project asked for `ducta[spark]>=0.1.1`, a release that cannot read
  the format-2 project it ships with; it now asks for the release that generated it.
- `ducta init project --help` said it writes `pipelines/<layer>.<domain>.<ext>`; it writes one
  `pipelines/<pipeline>.<ext>` per pipeline.
- `vite` dev server: `/health` was not proxied, so the setup wizard showed "undefined" under `npm run dev`.
- Web UI: a run whose checks all passed showed "8 err": every row of the quality table has a Severity
  column that reads ERROR, and the log level was guessed by keyword. Table rows are now an error
  only when the check failed, at that check's severity.
- `ducta template --list-templates` printed through the logger: a `Ducta: [hh:mm] INFO` prefix on
  every line and wrapped descriptions. It is plain output now.
- Config errors on a node named `transform`, `ingest` or `stream` lost the node's name
  (`pipelines/etl.nodes.inputz`); a typo in a node key is now compared with that node kind's keys
  (`inputz` → "did you mean 'inputs'", not 'input').
- A misspelled `run:` function was logged as "Security validation failed" and listed imported names
  (`Any`, `Optional`) as available; it now suggests the closest function defined in the module.
- A YAML syntax error named the source `"<unicode string>"` twice; it now gives the file, line and
  column.
- Web UI: after starting `ducta ui` in another workspace, the rail kept asking for the last project
  opened before (404 `Project '…' not found` in the console), and old workspace links redirected to
  it. The remembered project is now used only if the server has it, and forgotten otherwise.
- Web UI: no more "ResizeObserver loop" console errors from the pipeline top bar, truncated names
  and the stream throughput chart; and no more "preloaded but not used" font warning in Safari.

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

[Unreleased]: https://github.com/faustinolopezramos/ducta/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/faustinolopezramos/ducta/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/faustinolopezramos/ducta/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/faustinolopezramos/ducta/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/faustinolopezramos/ducta/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/faustinolopezramos/ducta/releases/tag/v0.1.0
