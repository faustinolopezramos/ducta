# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Ducta is **alpha**: APIs and configuration can still change between minor versions.
This file keeps what you need to upgrade (breaking changes, removals, security) and the
headline of everything else; `git log` has the detail.

## [Unreleased]

### Added

- **Streaming nodes can merge, quarantine and check every micro-batch**: `stream.output.mode:
  merge` upserts into a Delta sink, `stream.quarantine.reject_when` sets rows aside, and a
  node's `quality:` block now runs on every batch (it used to be ignored).
- **Streaming runs leave a journal and a sealed certificate**, and `alerts:` accept
  `stream_failed`, `stream_stalled` and `stream_quarantine`.
- **Windowed loads**: `write.partition_overwrite: dynamic` (Parquet, CSV, JSON, ORC) replaces
  only the partitions a run wrote, and `ingest.incremental: {column}` makes a declarative
  ingestion read only the run's `--start-date`/`--end-date` window. `ducta config validate`
  warns when a windowed read overwrites a partitioned output with the default.
- **Version combinations known to fail are reported before a run**: `ducta check` and the
  start of a local Spark session warn about Spark 3.5 on Python 3.14, Spark 4 on Java older
  than 17, pandas 3 and a Delta build for another Spark, each with its fix
  (`config validate --output-format json` lists them under `environment`).
- **Reproducible installs**: each release attaches `constraints-py3.X.txt` to its GitHub
  release, the exact versions it was tested with, for `pip install -c`.
- **Spark defaults that change results are named**: `ducta check`, `config validate` and the
  start of a local session warn while `settings.spark_config` leaves unset
  `spark.sql.ansi.enabled` on Spark 4 (an invalid CAST, a division by zero or an overflow
  stops the run where Spark 3.5 returned NULL) and `spark.sql.session.timeZone` (the
  machine's zone otherwise). Ducta does not change either.
- **A served model names the library versions it was registered with**: registration records
  them (Python, scikit-learn, xgboost…), and serving warns when the installed one differs —
  a scikit-learn pickle from another release only raises a warning nobody sees.
- **The UI database is backed up before a migration** (SQLite: `<file>.bak-<revision>`).

### Changed (breaking)

- **A run no longer copies its certificate to `~/.ducta/storage`** unless a StorageBackend is
  configured (`DUCTA_STORAGE_PATH`, or `DUCTA_STORAGE_BACKEND=s3`). The copy was made on every
  run of every project and never pruned; the certificate under the environment's output is
  unchanged, and copies already there still open in the web app.

- **Python 3.14 and Spark 4.2 are supported; Python 3.10 is not** (it reached its end of
  life in October 2026). `ducta[spark]` now installs Spark 4.2, which needs Java 17 or 21; Spark
  3.5 stays supported (`pip install "pyspark>=3.5,<3.6"`), Python 3.14 needs Spark 4. The Docker
  image runs Python 3.12 on JDK 21, from `anaconda/miniconda`.

- **A CSV round trip keeps its values**: Ducta reads CSV with `quote`/`escape` `"` and
  `multiLine: true`, and writes it without trimming spaces. A doubled quote or a line break in a
  value used to corrupt it or add a row, with the run reporting success. `multiLine` keeps a file
  in one Spark partition: set `multiLine: false` on a large file without line breaks in values.
- **Two datasets written to one path are an error** in `ducta config validate` (a warning if both
  only append, or if they are in different pipelines), and an unknown `fingerprint_mode` is rejected.
- **`--end-date` covers its whole day** on a timestamp column (it used to lose the last day):
  the window is `column >= start AND column < end + 1 day`. Runs over timestamp columns return
  more rows than before.
- **Checks that passed without checking anything now fail**: an unknown `test_type`,
  `rule_type` or `direction` is an ERROR; SQL `business_rules` count a NULL as a violation.
- **`ducta ui` / `ducta server start` refuse a non-local `--host` without authentication**
  (set `AUTH_ENABLED=true`, or pass `--allow-unauthenticated`). `ui --enable-terminal` is gone.
- **Pre-0.3 compatibility is removed**: old certificate, chain-state and quality locations
  (`.ducta/runs`, `.quality`...), `Ducta_*` environment variables (use `DUCTA_*`),
  type-wide database credentials (only `<SOURCE>_USER`/`<SOURCE>_PASSWORD`), `--format`,
  the gate's `block`/`warn` aliases and `fingerprint_mode: fast|full`.
- **A key written twice in the same block is an error**, with both line numbers.
- **`Context` takes mappings**, and the API database starts from a single migration (`0001`):
  databases created by earlier versions are not upgraded.
- **Removed, unused**: `PythonConfigLoader`, `SpecializedValidator`, `CrossValidator`, the
  `mlrun.mlflow` helpers, `api.core.file_watcher`, the `watchdog` dependency, and about 60
  other methods nothing called. `checkpointLocation` in a stream's `output.options` is
  rejected (use `streaming.checkpoint_location`).

### Security

- **The API answers only to the host names it should** (DNS rebinding): a request whose
  `Host` is not `localhost`, `127.0.0.1`, `::1`, the bound address or one in the new
  `ALLOWED_HOSTS` gets a 400 (WebSocket handshakes included). A web page could otherwise
  point a name it controls at 127.0.0.1 and read and write the workspace of a local
  `ducta ui`. Bound to `0.0.0.0` with no `ALLOWED_HOSTS`, no host is checked and the
  server warns at startup.
- **Cross-site requests cannot change state**: a `POST`, `PUT`, `PATCH` or `DELETE` whose
  `Origin` is neither the server's own nor in `CORS_ORIGINS` gets a 403. Routes without a
  JSON body (`git pull`/`push`, cancel, retry, schedule toggle…) used to run from any page.
- **One strict Content-Security-Policy everywhere**: outside production the UI was served
  with `default-src * 'unsafe-inline' 'unsafe-eval'`. The policy is now same-origin, with
  `'wasm-unsafe-eval'` for the ruff formatter and `blob:` workers for the editor; only
  `frame-ancestors` differs by environment.
- **UI dependencies**: dompurify 3.4.17 (critical advisory, via monaco-editor), zod 4.6.7
  and follow-redirects 1.16.2.
- **The `developer` role is documented for what it grants**: pipelines run inside the API
  process, so code a developer runs can read `JWT_SECRET_KEY`. The server says so at startup
  when authentication is on (`docs/server_api.rst`, `SECURITY.md`).
- **The AI features mask more keys in a failed run's error**: OpenAI/Anthropic (`sk-`), AWS
  access key ids, GitHub, Slack and Databricks (`dapi…`) tokens and private-key blocks were
  masked in code but not in the error text sent to the model.
- **TLS**: SQL Server verifies the server certificate by default, and PostgreSQL, MySQL and
  MariaDB do so unless the host is local. A server with a self-signed certificate needs
  `url_params: {trustServerCertificate: "true"}` (or `sslmode: require`); Ducta warns.
- **The SQL sanitizer blocks functions that reach the host** (`reflect`, `java_method`,
  `read_files`, `OPENROWSET`, `UTL_*`, `TRANSFORM ... USING`...) and queries that read files.
- **An ingestion node's `options` can no longer replace the checked statement or connection**
  (`query`, `dbtable`, `url`, `driver`...).
- **The `.env` is safer**: credentials cannot add lines to it, it is written readable by its
  owner only, the engine reads only a source's `<SOURCE>_USER`/`_PASSWORD` and copies nothing
  into `os.environ`.
- **A connection's `host` and `database` can no longer add parameters to the JDBC URL.**
- **No secrets in logs** (option and setting values are logged by name), and `env` cannot
  point outside the output folder.

### Fixed

- **`PUT /api/nodes/{name}` accepts a node exactly as `GET` returned it**: the read side
  turns `input`/`output` into `inputs`/`outputs` lists for the UI, and saving that back
  was refused ("key 'inputs' is not a node setting Ducta reads"). The quality block is
  still written back in its long form, so comments inside it are lost.

- **Declarative ingestion from Oracle**: the statement Ducta composes for `columns`, `where` or
  `incremental` aliased its subquery `AS q`, which Oracle refuses; the alias no longer has
  `AS` (accepted by every supported database).
- **XML on Spark 3.5 without spark-xml** says how to add the package: the check asked py4j for
  a Java *package*, which py4j answers for any name, so it always passed and Spark's own error
  came instead.
- **`--env` naming no declared environment warns**: `-e prodx` ran the base project, writing
  under `prodx/`, with only an info line. It still runs, now with a warning that lists the
  declared environments and the closest one.
- **New projects set `spark.sql.session.timeZone: UTC`**, so they no longer warn about the time
  zone on every run.
- **A served model also names a numpy or pandas of another major version** than the one it was
  registered with (a numpy 1 pickle does not load on numpy 2).
- **The quality history's file lock waits on Windows** instead of failing after ten seconds.
- **`mypy` runs with the project's settings on Python 3.12+**: numpy 2.3+ stubs stopped it.
- **A project, database or model registry from a newer Ducta is named as such**: a
  `ducta.yaml` with `version: 3` said "No Ducta project here"; it now says to upgrade
  Ducta. A UI database migrated by a newer Ducta failed at startup with Alembic's "Can't
  locate revision"; it now says which Ducta migrated it. A registry entry with a field this
  Ducta does not know no longer fails to load.
- **A failed query on Spark 4 no longer prints a JSON copy of itself** (one was 18,892
  characters, with the JVM stack) before Ducta's own error message, in a local run.
- On Spark 4 without the `connect` extra, `python -c`, `python -m` and worker processes that
  imported Ducta exited with success having done nothing.
- Spark 4: Delta loads the build for the running Spark minor, a Kafka source missing its
  connector names the Scala 2.13 package, and XML is read with Spark's own reader (Spark 3.5
  still needs `spark-xml`, whose suggested coordinate now exists).
- Console log lines are literal text: `ducta[api]` printed as `ducta`, and a `[/path]` in a message
  raised an error that lost the message. Lines that had lost their tag now show it
  (`[node_status] node_id=… status=…`).
- In the server, a project's `spark_config` no longer stays on the session for the next project.
- An output holding only Spark's `_temporary` (a write that never committed) no longer counts as
  materialized. The error when the Spark JVM dies points at memory, and a read without PySpark
  says how to install it.
- `overwrite_strategy: replaceWhere` failed outside Unity Catalog because the run's window
  never reached the writer.
- A hybrid pipeline waits for its streaming phase before reporting; stopping a stream while
  it starts leaves no query running; Ctrl+C on `stream run --mode sync` stops gracefully.
- `settings.mlops_path` expands `${paths.output}` and `${env}`; `settings.quality.gate` now
  honours `on_fail`; the server no longer unloads installed packages after a run.
- An interrupted run is recorded as failed instead of sealing a `success` certificate.
- Reviews of `ducta.check`, `ducta.mlrun`, `ducta.console`, `ducta.core`, `ducta.gate` and
  `ducta.setting` fixed data-loss and false-pass cases: an unreadable quality history, a model
  registration swallowed while the node reported success, a dead lock owner blocking runs,
  a driver JAR used without checking its `sha256`, and trailing newlines accepted in names.

### Dependencies

- Newer majors accepted after running the test suite on them: `rich` 15, `bcrypt` 5, `redis` 8,
  `optuna` 5, `anthropic` 2, `pyarrow` 26 (the first with Python 3.15 wheels), `ruamel.yaml`
  0.19. `pandas` stays below 3: it turns a missing text value into the string `'NaN'` on its way
  to Spark.

## [0.3.0] - 2026-10-24

AI-assisted pipelines, streaming you can see, and a run table. Mostly additive.

### Changed (breaking)

- `delta_stream` reads appended data unless you set `input.options.readChangeFeed: true`.
- **CLI exit codes changed**: a failed `--sweep`/`--search` trial exits `4`, a failing
  `quality run` check `3`, `ai apply` without a terminal and `--yes` `3`, and
  `init ingestion test` exits `5` when it could not try the connection. A script that checks
  for `1` must check the new code.
- One experiment per pipeline (an execution is a run in it).
- `ducta.setting.project_*` modules moved to the `ducta.setting.project` package.

### Security

- The file browser no longer lists or serves `.env`.
- Credentials in a text are found before a file is sent to a remote model.

### Added

- **`ducta ai`**: draft, fix, extend, review, explain, add quality checks and document
  pipelines with a local or hosted model; `ducta ai eval` measures a model. The model
  proposes; Ducta writes and verifies.
- **Ducta Architect and Sentinel** (design several pipelines; open incidents and propose safe
  re-runs), and `ducta skill install` for coding assistants.
- **A table of all your runs** (`ducta.mlrun.run_summary`) linked to run certificates.
- **Visible streams**: a live table in the terminal, `ducta stream plan`, and Start/Stop in
  the app. `rate` and `socket` sources and a `memory` sink.
- **`ducta list` and `ducta check`**, and `ducta config validate --output-format json`.

### Fixed

- Streaming reliability (false success, failed upstream, shutdown, checkpoints), ML tracking
  (hyperparameters, `--search`, `model promote`, `model gc`), quality checks, TOML/JSON
  projects in the web app, `--reuse-upstream` over a declarative ingestion, and many web
  app issues.

### Dependencies

- Python 3.13 installs without building numpy.

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
