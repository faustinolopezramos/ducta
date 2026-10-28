# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Ducta is **alpha**: APIs and configuration can still change between minor versions.
This file keeps what you need to upgrade (breaking changes, removals, security) and the
headline of everything else; `git log` has the detail.

## [Unreleased]

### Added

- **Stream nodes can merge, quarantine and check every micro-batch.**
  `stream.output.mode: merge` upserts each batch into a Delta sink by `merge.keys`
  (`merge.dedupe_order_by` keeps the latest row per key); `stream.quarantine.reject_when`
  sets rows aside; the node's `quality:` block now runs on every batch and a blocking
  gate quarantines the whole batch while the stream goes on (it used to be accepted and
  ignored). Delta writes are idempotent per batch.
- **Streaming runs leave a journal and a certificate.** Each run writes
  `<output_path>/<env>/.ducta/streams/<pipeline>/<run_id>/` (`run.json`,
  `batches.jsonl`) and, when it ends, a sealed Run Certificate (schema `1.8`) with each
  node's batches and rows read, written and quarantined.
  `GET /executions/{id}/streaming` falls back to the journal once no engine holds the
  stream, and the `adaptive` trigger starts from the previous run's durations.
- **Live stream alerts**: `alerts:` rules accept `stream_failed`, `stream_stalled` and
  `stream_quarantine`. New settings: `streaming_quality_report_every`,
  `streaming_health_interval_seconds`, `streaming_quarantine_alert_interval_seconds`,
  `stream_journal_dir`.

### Changed (breaking)

- **`ducta.check` results that used to pass without checking anything now fail.** An unknown
  `test_type` (`statistical`), `rule_type` (`business_rules`) or `direction`
  (`dataset_completeness`) is an ERROR instead of "All ... passed"; `schema_drift` with no
  `baseline_schema` is a WARNING ("nothing was compared") instead of a pass that claimed to
  store a baseline; `dataset_completeness` with a `distinct_limit` smaller than either
  side's distinct values is a WARNING ("inconclusive") instead of comparing two arbitrary
  subsets. SQL `business_rules` now count a row as a violation unless the rule is TRUE for
  it, so a NULL (`amount > 0` with a null amount) is a violation, as it already was for
  `rule_type: python`. A `format: json` quality output with a cloud `base_path`/`output_path`
  (`s3://`, `abfss://`, `gs://`, `dbfs:/`) is refused with a message; it wrote to a local
  folder named `s3:` and never reached the bucket.

- **`ducta ui` / `ducta server start` refuse a non-local `--host` without authentication.**
  The server runs pipelines; `--host 0.0.0.0` used to serve it open to the network and the
  API's exposure warning never fired (it reads `HOST`, which the command did not set). Set
  `AUTH_ENABLED=true` (and `JWT_SECRET_KEY`), or pass `--allow-unauthenticated` if the
  exposure is intended (exit code 6 otherwise).
- **`ducta ui --enable-terminal` was removed.** It only set a variable nothing read: there is
  no web terminal.
- **`ducta profile --output` refuses to replace an existing file**; pass `--force`.
  With `--output-format json` stdout is the JSON document alone (it used to be followed by
  the YAML spec, which made it unparseable).
- **`checkpointLocation` is rejected in a stream's `output.options`.** It silently replaced
  the checkpoint Ducta reserved for the node; set `streaming.checkpoint_location`.
- **`StreamingValidator.validate_pipeline_compatibility` was removed**, with the
  validator's `max_batch_nodes`/`max_streaming_nodes` arguments (nothing called it).
- **`ducta.setting` lost its unused legacy code.** Removed: `PythonConfigLoader` and
  `ConfigLoaderFactory(allow_python=...)` (a `.py` config never runs; the factory reads
  YAML, JSON and TOML), `SpecializedValidator`, `CrossValidator`, `ProjectSchema`,
  `ConfigRepositoryError`, `ActiveConfigNotFound`, `CanonicalEnvironment`,
  `FALLBACK_CHAINS`, `get_fallback_chain`, `get_sandbox_developer`,
  `is_valid_environment`, `allowed_environments`, `is_allowed_environment` (and the
  undocumented `DUCTA_ALLOWED_ENVS`), `Context.from_json_config` and `deep_merge_dicts`.
- **`Context` takes the five documents as mappings.** It no longer loads files or accepts
  `allow_python_config`, and no longer merges an inline `environments:` block (a
  format-2 `settings:` rejects it); `ml_info` must be a mapping (a file path is rejected
  with a pointer to `settings.ml_info`). Projects are unaffected:
  `compile_project` always produced mappings.
- **`ducta.gate` lost code nothing used or that lived in the wrong layer.** Removed:
  `SparkWriterMixin` (folded into `BaseSparkWriter`), `JDBCConnector.discover_tables` and
  `ConnectionManager.prefetch_drivers`. `IngestionService`, `ConnectionSpec`,
  `IngestionServiceError`, `SUPPORTED_TYPES` and `DEFAULT_PORTS` moved to
  `ducta.setting.connections` and are no longer exported by `ducta.gate.gateway`.

### Security

- **PostgreSQL, MySQL and MariaDB check the server's certificate unless it is on this
  machine.** Remote hosts get `sslmode=verify-full` / `sslMode=VERIFY_IDENTITY` (MariaDB:
  `verify-full`), as SQL Server already did. A server without a certificate needs
  `url_params: {sslmode: require}` (`sslMode: REQUIRED`), and Ducta warns when it is relaxed.
  `localhost`, `127.0.0.1` and `[::1]` keep the driver's default. Oracle and Snowflake are
  unchanged. Deleting a connection (`ducta ingest`, API) now removes its `<NAME>_USER` and
  `<NAME>_PASSWORD` from `.env`, which is written atomically and is never readable by others.
- **The SQL sanitizer refuses functions that reach the host and queries that read files.**
  `reflect`, `try_reflect` and `java_method` (Spark can call any static JVM method:
  `System.getenv` returned the process's secrets), `read_files`, `read_kafka`,
  `http_request`, Postgres `lo_*` / `dblink`, SQL Server `OPENROWSET` / `OPENQUERY`, Oracle
  `UTL_*` / `DBMS_*` package calls, Spark's script transform (`TRANSFORM … USING 'cmd'`, which
  runs a shell command on the executors), the `IDENTIFIER('…')` clause (it hid a file read in a
  string), and `FROM csv.`path`` or a quoted path in table position (a local file read as a
  table) used to pass. Column names and aliases such as `dbms_id` or `` `ratio/x` `` still do. The same check guards business rules, `merge.delete_when`
  and `quarantine.reject_when`, where a function call was a one-bit oracle on server secrets.
- **An ingestion node's `options` can no longer replace the checked statement or the
  connection.** They were merged after the sanitized `query`/`dbtable`, so `query`, `dbtable`,
  `url`, `driver`, `sessionInitStatement` or `prepareQuery` reached Spark in
  place of what was checked. They are refused when the project is validated (with file and line)
  and again when the node runs.
- **A connection's credentials cannot add lines to the `.env`.** A line break in a username or
  password wrote extra entries (`JAVA_TOOL_OPTIONS`, `AUTH_ENABLED`…) that the gateway loaded
  into the process and the API server read as settings. They are refused, and the `.env` is now
  written readable by its owner only (it was `0644`). **The gateway now loads only the
  `<SOURCE>_USER` and `<SOURCE>_PASSWORD` of the source it opens** from a `.env`; any other
  entry in that file used to be copied into `os.environ` and no longer is.
- **A connection's `host` and `database` can no longer add parameters to the JDBC URL.** They
  were pasted into it as written, so `database: "shop?autoDeserialize=true"` or a host such as
  `evil:3306/x?…#` added driver options or pointed the URL at another server, and the connection
  form only checked that the fields were not empty. `host` must be a name or address and
  `database` letters, digits and `_ $ . -`; `url_params` names and values are checked too. The
  form, `ducta init ingestion` and `sources.yaml` all go through the same rules.
- **SQL Server verifies the server's certificate by default** (`trustServerCertificate=false`);
  it was `true`, so the connection was encrypted to whoever answered. **A server with a
  self-signed certificate now needs `url_params: {trustServerCertificate: "true"}` on its
  source**, and Ducta warns when a source sets it. A connection that fails on an untrusted
  certificate says so and names that setting.
- **Option and setting values are no longer written to `logs/ducta.log`.** A writer's extra
  options and a Spark setting that failed to apply were logged as `name=value` at DEBUG, and that
  file keeps everything for 7 days: `fs.azure.account.key…` or `fs.s3a.secret.key` ended up in
  it. They are logged by name.
- **`env` must be usable as a folder name.** `--env ../../x`, `env: "/etc"` in an API execute
  request or in the configuration wrote a run's outputs outside the output path (`overwrite`
  removes what is there). The `Context` refuses a name with a path separator, `:`, `..` or a
  control character when it loads, and the output paths refuse it again where they are built.
- **The engine no longer copies a `.env` into the process environment, and reads only the
  project's own.** It loaded every entry of the `.env` in the working directory, its parent or the
  home folder into `os.environ`, so the file could set variables for the JVM
  (`JAVA_TOOL_OPTIONS`) and a stale line outlived a changed environment variable. It now reads the
  `<SOURCE>_USER` / `<SOURCE>_PASSWORD` pair from the `.env` of the project the `sources.yaml`
  belongs to (the current project's when `sources_path` points outside it, which is where
  `ducta init ingestion setup` writes them), after the environment, and copies nothing into it.
  The values are written single-quoted, so a password with surrounding spaces or quotes is
  read back exactly.

### Fixed

- **`ducta.check` review.**
  - *Sanity gate:* a `sanity_gate` that never evaluates (`enabled: false`) or cannot be
    evaluated (`max_errors: null`) no longer lets ERRORs through. Declaring a gate turns
    off fail-fast; if the gate then decided nothing, the node ran on bad data. A disabled
    gate now leaves the node judged as if none were declared, and a broken one fails the
    node, as the data-quality phase already did.
  - *Storage:* history is replaced atomically under a sidecar lock; a process killed
    mid-write used to leave a truncated `history.json` that failed every later run. An
    unreadable history or baseline is treated as absent (the file is kept as
    `history.json.corrupt-<time>`), and a history append that fails is listed in the
    report's `persistence_warnings`. A non-JSON history that exists but could not be read
    is no longer overwritten with a single row. Cloud locations (`s3://...`) keep their
    scheme instead of becoming `s3:/...`.
  - *Checks:* `drift_detection` compares date, datetime and null categories with the
    stringified keys of its baseline (a stable date column scored as drift) and its
    chi-square distance compares shares, not counts; `dataset_completeness` ignores nulls
    and NaN; unquoted YAML dates in `holidays` count as holidays and an unreadable one is
    an error; a naive Spark timestamp is read in the driver's time zone, not as UTC.
  - *Service:* `ducta quality summary` shows the score trend (it was always empty), and
    `validate_node_config` validates a check by its `type:` (`orders_nulls: {type:
    null_rate}` was "unknown").
- **`ducta.mlrun` review.**
  - *Model registry:* a hyperparameter that is a list, tuple or dict of scalars
    (`hidden_layer_sizes=(50,)`, `class_weight={0: 1, 1: 5}`) and numpy scalars (`np.int64`,
    `np.float32`, also as metrics and in `log_metric`) are accepted. Before, they failed the
    registration, which `persist_model` swallowed, leaving an unregistered local pickle while
    the node reported success. The number of a deleted version is never issued again: the
    registry keeps `models/version_counters.json` (a registry written before it learns the
    numbering on its first delete), so a pipeline pinned to `version: 3` or a certificate
    naming v3 cannot silently point at another artifact.
  - *Experiments:* `log_artifact` without a destination wrote every artifact of a run to the
    same path, so the last one replaced the others; each now gets `artifacts/<run>/<file>`.
    `delete_run` also removes the run from the metrics index and deletes its metric files:
    `search_runs` with a metric filter kept returning deleted runs. With
    `execution_mode: databricks`/`distributed` the MLOps start-up no longer fails on
    `storage.base_path`.
  - *Search:* a `{min, max}` range of whole numbers is sampled as whole numbers under
    `random`/`bayesian` (it gave `n_estimators=259.01`, which sklearn rejects; `grid` was
    already right). A conditional parameter (`depends_on`) is suggested to Optuna under one
    name per parent value, since Optuna fixes the choices of a name for the whole study.
  - *Training:* binary metrics score the greater label as the positive class; a target of
    `'yes'/'no'` or `{0, 2}` failed with `pos_label=1 is not a valid label` after the whole
    search had run.
  - *Storage and locks:* `LocalStorageBackend` reads, `exists` and `delete` find the file a
    write to a suffix-less path created (`write_json(x, "foo")` makes `foo.json`), so
    transaction rollback no longer misses it. A lock whose owner is a dead process on this
    host is taken at once instead of after five minutes (a `SIGKILL` made every
    `end_run`/`register_model` time out for that long); a live owner is still never robbed.
- **`ducta.console` review.** The log file (always DEBUG, kept a week) is created readable by
  its owner only and its messages pass through the AI features' credential redaction. A
  project on a world-writable or foreign-owned folder (a Docker bind mount) no longer fails
  with "World-writable file detected" when run from another directory; system folders are
  still refused, now also on macOS where `/etc` is `/private/etc`. A failed `ducta template`
  removes what it wrote, so the same command can be run again. `ducta stream run` no longer
  takes an unanswered status for "finished" (exit 0): after three misses it reports the
  pipeline as lost. `ducta init ingestion setup` asks for the connection name again until it is
  valid. A name ending in a newline (`$` accepts it) is refused in project, run, connection,
  node, draft and job names; a connection called `db\n` used to write a broken `.env`.
- **`ducta.core` review.** An interrupted run (Ctrl+C, `SystemExit`) is now recorded as
  failed: it used to seal a `success` certificate and write the chain state, so
  `reuse_upstream` would skip the pipeline. A node with `run_in_process: true` in a
  **sample run** wrote the real dataset and read every row (its worker rebuilt the Context
  from the project and only got `output_path`); the worker now receives the parent's
  `sample_rows`, scratch paths, certificate and chain directories and its
  `allow_python_config`. A failure between taking the run lock and starting the run, or on a
  later key, no longer leaves the outputs locked; the file lease store renews a lease
  without ever removing it (a run starting at that instant could take the same output) and
  its `ttl_seconds` must be well above the clock skew between hosts. A `retry` wait is capped
  at 60 s and ends when the node is cancelled. Frames served from `in_memory_handoff` are no
  longer unpersisted by the first node that reads them. Verifying an unsigned certificate
  with a key says that authorship is not attested. A prefix in `allowed_module_prefixes`
  without a final dot names a package (`nodes` no longer admits `nodes_evil`); trailing
  newlines are refused in module, function and table names; the chain-state marker is
  written atomically.
- **`ducta.gate` review.** A host, database or name written with a trailing newline no longer
  passes the JDBC and path validators (`$` accepted it). `driver.jar`, `driver.version` and
  `driver.maven` can no longer point outside `lib/jdbc/` or at a non-`https` URL. A driver JAR
  is downloaded to a temporary file, checked against its `sha256` and only then renamed; one
  already in the folder is checked too (a tampered or half-downloaded one is fetched again),
  and the download has a timeout. A reader's `partition_filter`, a writer's `replace_predicate`
  and any `replaceWhere` option must be a plain predicate (they reached Spark's SQL parser
  as they were). `MERGE` quotes its key and update columns and no longer breaks on a key named
  `count`. A write skipped by `fail_on_error: false`, a dataset replaced by `None`
  (`fill_none_on_error`) and a model artifact that could not be saved are recorded as gaps in
  the run's evidence; model artifact errors now respect `fail_on_error`. An `append` or `merge`
  no longer leaves a stale in-memory handoff frame to be read back. A Delta input read as of a
  timestamp is no longer fingerprinted as the latest version.
- **`ducta.setting` review.** A node input map whose parameter is called `schema`, `path`,
  `format` or `options` still gets its dependency edges. `environments:` blocks match
  `--env` by normalized name (`production`, `Prod`), and two blocks naming the same
  environment are an error. `${environment}`, `${input_path}` and `${output_path}` come from the
  Context, not the process environment (a shell `environment=` no longer rewrites the
  active one). A
  `quality.extensions` module that fails to import stops the run instead of running
  without its checks. A Spark session with a live stream is never expired by the idle
  timeout, and one shared by several config keys is stopped with the last. Connections
  whose names differ only in case are refused (they shared one `.env` login),
  `sources_path` must stay inside the project, and an empty `sources:` no longer crashes.
  One uninterpolable `ml_info` value no longer leaves the rest unresolved.
- **Stopping a stream while it starts no longer leaves a query running**, and a live
  query's checkpoint is never deleted.
- Streaming correctness: `stream.transform: <name>` (the short form) failed at start;
  checkpoints on `s3a://`, `s3n://`, `wasb://`, `wasbs://` were treated as local paths;
  the `adaptive` trigger ignored idle reports; mapping/list options (Kafka `assign`,
  `startingOffsets`) are sent as JSON; a failing writer logs option names, not values.
- **`settings.mlops_path` expands `${paths.output}`, `${paths.input}` and `${env}`**
  (it created a directory literally named `${output_path}`, shared by all environments).
- **Ctrl+C on `ducta stream run --mode sync` stops the queries gracefully** (exit 0), including
  the streaming phase of a hybrid pipeline. Interrupted before any query was running, it says
  nothing was stopped and exits 4 instead of reporting a clean stop.
- **The server no longer unloads installed packages after a run.** Its cleanup removed
  numpy, which numpy 2 cannot load twice, so the next run failed preflight. Only the
  project's own modules are unloaded.
- **A Delta `replaceWhere` predicate escapes its column** (`` `col` BETWEEN … ``, and
  `` `meta`.`event_date` `` for a nested one); the
  column name was pasted into it as written. It is now built by the one function Unity
  Catalog outputs already used, and the XML reader no longer logs a stray warning on every
  successful read.
- **Pre-commit review.** `--host ""` counts as an open address for `ducta ui` / `ducta server
  start` (uvicorn binds it to every interface): it no longer passes as local. A traceback
  written to `logs/ducta.log` is redacted like the message (a driver error echoing
  `password=…` went in as it was), and a rotated log is zipped readable by its owner only. A
  JDBC source that turns TLS off another way (`useSSL`, `ssl`, `useSsl`, `encrypt: false`) is
  warned about like a weak `sslMode`. A quality output on a cloud `output_path` with no
  `quality.output.format` writes parquet instead of failing every node (an explicit `json`
  still fails). `ducta stream run` treats an empty status as unanswered, not finished. The ML
  storage's `write_dataframe` retries transient errors again. A range whose `max` is a float
  is sampled as floats, and a `log: true` range starting at 0 is refused up front. A node
  cancelled while waiting to retry is reported as cancelled. A node's output handed to the
  next nodes in memory is no longer released when the node ends. Two runs taking over the
  same dead lease guard can no longer both hold the lease.
- **Internal:** `ducta.gate.sql.validate_predicate` is the public home of the predicate
  check (business rules, merge `delete_when`, stream `reject_when`), so `gate` no longer
  imports from `check` and `check` no longer reaches into the sanitizer's internals;
  `gate` records evidence gaps through the ledger's public `note_gap`; the in-memory handoff
  store uses one key (`_ducta_df_handoff`) for dict and object contexts; the input path
  resolution moved to `ducta.gate.input_paths` and the fingerprint policy to
  `ducta.gate.fingerprinting`; and `ducta.setting.project.loader` is split into `reader`, `overlay`,
  `validation` and `compiler` (`loader` builds the `Context` and re-exports every name it
  exposed); duplicate merge/leaf helpers are now one each in `ducta.setting.utils`.

## [0.3.0] - 2026-10-24

AI-assisted pipelines, streaming you can see, and a run table. Mostly additive; read the
breaking changes below.

### Changed (breaking)

- **`delta_stream` reads appended data unless asked for the change feed.** A node that
  relied on it enabling CDF must set `input.options.readChangeFeed: true`
  (`auto_enable_cdf` only applies then).
- **CLI exit codes are consistent.** A failed `--sweep`/`--search` trial exits `4` (was
  `1`); a failing `quality run` check exits `3` (was `1`); `quality validate-config`
  outside a project exits `2`; `ducta ai apply` without a terminal and without `--yes`
  exits `3` (was `0`); `ducta init ingestion test` exits `5` when it could not try the
  connection and `4` when it failed. A script that checks for `1` must check the new code.
- **One experiment per pipeline.** Every execution used to create its own experiment; an
  execution is now a run in its pipeline's experiment. Older experiments stay as they are.
- **`ducta.setting.project_*` modules moved to the `ducta.setting.project` package**
  (`project_loader` → `ducta.setting.project.loader`, and likewise `context`, `decompile`,
  `defaults`, `files`, `inspect`, `schema`). Public names are unchanged; only imports of
  the old module paths fail.
- **`ducta.console` exports what `__all__` names**; the argument validators stay in
  `ducta.console.validation`, and the unused `validate_mode`, `validate_format` and
  `validate_timeout` were removed.

### Security

- **The file browser no longer lists or serves `.env`.** `GET /api/workspace/files/content`
  returned it in full (database credentials, `DUCTA_CERTIFICATE_KEY`). `.env` and
  `.env.*` are hidden and refused (403) for read, write and delete; templates
  (`.env.example`, `.env.sample`, `.env.template`, `.env.dist`) are still shown.
- Credentials inside a text are found before a file is sent to a remote model (connection
  strings, SAS `sig=`, private keys, JWTs, short passwords), and the scanners are linear
  on long text. The pipeline status no longer carries the pipeline definition (broker
  credentials included), which `ducta stream status --format json` printed.

### Added

- **`ducta ai`: draft, fix, review and explain pipelines with a model**, local (Ollama) or
  behind an API key: `new`, `fix`, `extend`, `review PIPELINE NODE`, `explain` (why a run
  failed), `quality` (checks proposed from the data and proven on it), `document`
  (descriptions for undocumented datasets, pipelines and nodes), `setup`, `apply`. The
  model proposes; Ducta writes and verifies. The web app has *Explain with AI* on a
  failed run and a draft dialog whose job survives closing it.
- **`ducta ai eval` measures a model** on ten fixed cases, also over HTTP for admins.
  Token usage is shown at the end of each command; `ai: {enabled: false}` in a project
  keeps AI away from it; hosted endpoints are retried up to twice on `429` and transient `5xx`.
- **Ducta Architect** designs several pipelines first and builds them after. **Ducta
  Sentinel** opens incidents for failed, late and slow runs and proposes safe re-runs.
  `ducta skill install` puts an agent skill (Agent Skills format) where Claude Code,
  Codex, Gemini CLI, Copilot and other assistants look; `--agents` adds both agents for
  Claude Code.
- **A table of all your runs**: `ducta.mlrun.run_summary` in the format you choose, and an
  *All runs* view in Models › Experiments. A tracked run and its certificate point at
  each other.
- **Running a stream is visible**, in the terminal (a live table, `stream plan`) and in
  the app (Start/Stop stream, status dots on the canvas, node cards with restart).
  `rate` and `socket` sources and a `memory` sink make streams easy to try.
- **`ducta list` and `ducta check`**: the two things you do first in a project.
  `ducta config validate --output-format json` prints one JSON document on stdout.

### Changed

- `pip install "ducta[ai]"` is enough for `ducta ai` (no `ducta[api]`).
- `persist_model(metrics=...)` also logs them on the tracked run; `ducta.MLNodeContext`
  is public.
- CLI: `ducta` alone says where you are and what to run; errors say what to do; `-e` and
  `-p` work in every command; logs go to the project's `logs/ducta.log`; `ducta start
  --help` groups its options; `ducta stream run` ends with a summary and prints no
  harmless Spark warnings; `DUCTA_CONSOLE=compact` gives an optional compact view.
- Streaming: a stalled query is a warning, not an error, and a streaming run is not bounded
  by `execution_timeout_seconds`.
- Web app: run lists show only the open workspace's projects; the first visit starts in
  the environment where the runs are; `GET /api/mlops/experiments?pipeline=` filters.

### Fixed

- **Streaming reliability**: a run no longer reports success when a node never started;
  a failed upstream stops its dependants; shutdown stops `partial_failure` pipelines; a
  finished query frees its checkpoint; `delta_stream` no longer alters the table it
  reads; `trigger: adaptive` works; server-side streams are not stopped after
  `execution_timeout_seconds`; `clear_pipeline_checkpoints` clears what the pipeline uses;
  `ducta stream run`/`start` keep a stream running; `stream stop --timeout` reaches the
  engine.
- **ML tracking**: a run records the hyperparameters its model really has; `--search`
  trains what each trial asks for; `config validate` rejects a malformed
  `hyperparams_config`; no false `ERROR` for an ML pipeline without a search; Models ›
  Experiments shows metrics; `model promote … production` without `--env` applied no
  promotion policy, and `model gc` ignored `settings.mlops.gc` (a project keeping models
  longer than 90 days lost them).
- **Quality and checks**: the SQL check scans `TRUNCATE` structurally again; a blocking
  gate on a `run_in_process: true` node stops the node; `ducta quality run` prints its
  report on failure; preflight warns about `use_pandas` and stream-node `quality` with no
  effect; `alerts[].when: [stale]` is refused.
- **Projects and CLI**: TOML/JSON projects work in the web app and `ducta ui` (no second
  `ducta.yaml` beside a `ducta.toml`); `ducta ai …` finds the project above the current
  directory; `ducta config convert --out` wrote relative to the project root; `pipeline-info` exited `0`
  for a pipeline that does not exist; `--reuse-upstream`
  reuses a chain that starts with a declarative ingestion; a node without `outputs` runs;
  generated projects keep `.env` out of git; the AI builder rejects a pipeline name that
  is a path; comma-separated list settings (`CORS_ORIGINS`) work.
- **Web app**: comments survive adding/removing nodes on the canvas; Connections work in a
  workspace of several projects; a large Delta table's preview no longer reads every data
  file; "Needs attention" drops a failure once a later run fixed it; the CLI is readable on
  light terminals; many small UI fixes.

### Dependencies

- Python 3.13 installs without building numpy (3.13 takes numpy 2.1+; 3.10–3.12 keep 1.x).
  `uvicorn`, `aiosqlite`, `asyncpg` and `prometheus-client` accept newer releases.

## [0.2.0] - 2026-10-10

Configuration format 2 (`ducta.yaml`, the catalog and `pipelines/`) replaces format 1,
which is no longer read, and `ducta template` writes the new format directly.

### Security

- **No known vulnerabilities in the installed dependencies** (`pip-audit` on a clean
  `ducta[all]` install reported 28 distinct advisories before): `mlflow` to `^3.15.0`,
  `pyarrow` to `>=23.0.1,<25` (CVE-2026-25087, use-after-free in Arrow C++), dev-only
  `pytest` to `^9.0.3`. The CI's dependency audit is blocking again.
- **API permissions tightened.** Deep preflight needs `pipeline.execute` (it runs project
  top-level code); a Git URL as a source needs `repository.write` (any authenticated user
  could make the server clone a repository); model promotion and deletion have their own
  permissions (`model.promote`, `model.delete`); testing an unsaved ingestion connection
  needs `ingestion.write`. A test fails if a route that writes is reachable by a viewer.
- **Run certificates measured far less than they claimed on Spark.** The fingerprint code
  was written for pandas: on Spark `row_count` was always `null`, the default mode degraded
  to the first 100 rows (a corrupted last row gave an identical fingerprint) and `full`
  hashed only the schema. Fingerprinting is now engine-native (an order-independent
  multiset digest on Spark that detects a changed, duplicated or deleted row); modes are
  `exact` (default), `sample` and `schema`. **Every fingerprint value changes**, each
  records its `engine` and `algorithm`, and comparisons across algorithms report *not
  comparable* instead of a data change. A failed fingerprint is no longer silent: it marks
  the certificate `evidence_complete: false`.
- **`python-jose` replaced with `PyJWT`** (python-jose pulls in `ecdsa`, whose Minerva
  timing vulnerability CVE-2024-23342 has no fix); UI dependencies with advisories
  (`react-router-dom`, `axios`, `dompurify`) upgraded; the web terminal now signals the
  shell's whole process group on disconnect; `SECURITY.md` added.
- `${VAR}` credential guard now catches obvious names; a certificate's signature can no
  longer be removed without `verify` noticing.

### Changed (breaking)

- **`-e` is `--env` on every command.** On `ducta stream status` and `ducta stream stop` it
  used to mean `--execution-id`, which now has the short form `-i`. A script running
  `ducta stream stop -e <id>` fails instead of stopping anything.
- **Saving from the web app or the API no longer commits.** Every write is still validated
  against every environment; committing is the user's call. The concurrency token
  (`commit_sha`/`expected_sha`) is now a hash of the file's content, so an uncommitted
  edit by someone else is a `409` too.
- **Quality reports default to `<paths.output>/<env>/quality/`**, not the hidden
  `.quality/`. An environment that already has `.quality/` (and no `quality/`) keeps using
  it; `settings.quality.output.base_path` still overrides both.
- **A declared train/test split is enforced.** A node bound to a split that finishes
  without applying it fails before its output is written (it used to warn);
  `settings.split_enforcement: warn` restores the warning.
- **MLflow 3.15 or later** (`mlops` extra). MLflow 3 refuses a local-folder tracking store
  unless `MLFLOW_ALLOW_FILE_STORE` is set; Ducta sets it for a configured local store and
  recommends `sqlite:///.../mlflow.db`.
- **A dataset's contract is `quality:`, not `checks:`.** `checks:` on a catalog entry is an
  error that says to rename the key.

### Removed

- **Loading configuration format 1** (`environment.yaml` + `config/*`) and layered
  projects, in the CLI, the API and the web app, with `ducta config migrate` (use it from
  commit `7696708` to convert a 0.1.x project), `ContextLoader`, `FlexibleConfigResolver`,
  `LayeredProjectDetector`, `ConfigDiscovery`, `AppConfigManager` and the CLI options
  `--layer-name`, `--use-case`, `--config-type`, `--interactive`, `template --format` and
  `--legacy-config`. A format-1 project stops with exit code 2 and the command that
  converts it.
- **The legacy certificate switches** `enable_run_certificate` and
  `require_run_certificate`: `evidence_level` (`off | record | required | signed`) is the
  only way to choose how much evidence a run leaves. The `Ducta_CERTIFICATE_KEY`
  spelling is no longer the name; use `DUCTA_CERTIFICATE_KEY`.
- **The specialized context hierarchy** (`ContextFactory`, `MLContext`, `StreamingContext`,
  `HybridContext`, `BaseSpecializedContext`): exported but constructed by nothing, so
  their validations never ran. The useful part (streaming output formats checked against
  the format policy, a warning for inert `spark.streaming.*` keys) lives in preflight.

### Added

- **Configuration format 2.** A project is `ducta.yaml`, `catalog.yaml` (every dataset
  once) and one `pipelines/<name>.yaml` per pipeline: 3 files instead of 15 for the
  medallion scaffold. Unknown keys are errors with file, line and a suggestion, all
  problems are reported at once, environments are deep-merged overrides of the whole
  project, and it compiles to the same five documents the engine always read. Around it:
  TOML and JSON project files, `defaults`, pipeline templates (`extends`/`params`) and
  node templates (`use`/`with`), a catalog split by layer, quality profiles in
  `quality/profiles.yaml`, inline checks, typed check parameters, and `ducta config show |
  explain | diff | convert`, `ducta init project`, `ducta.load_project()`.
- **Data safety and evidence**: a run lock (one writer per output dataset),
  `write_mode: merge` (Delta upsert by key), `incremental: {column: …}` inputs, automatic
  Delta Lake on local sessions, `evidence_level`, `fingerprint_mode: auto` (Delta inputs
  identified by commit version, windowed inputs hashed over the window; 0.97 s → 0.09 s on
  20M rows) and `exact_crypto`, `on_missing_input: skip | fail`, and `certify verify`
  saying what it proved (`integrity` vs `authenticated`).
- **ML and serving**: `ml_stage: serving` scores with a registered model (streaming nodes
  too), `train_with_search`, `tag_partitions`, `split_dataframe` on Spark,
  `persist_model(native=True)`, Spark ML models in the registry, SHA-256 of each artifact
  at registration, `prediction_contract` checks, `ducta experiment runs | show | compare`,
  `ducta config show --ml`, `ducta[boost]`, and the `ml_basic`, `hybrid_basic`,
  `ml_scoring` and `streaming_basic` templates.
- **API and web app**: the app is laid out like a code editor (explorer, canvas or editor,
  inspector); an `operator` role; endpoints to validate unsaved edits and edit a
  pipeline; live streaming status; the UI follows the user's permissions; ML evidence in
  the certificate view; `ducta quality validate-config --node N [--env E]`.
- A mistyped command names the closest one; `--output-format` is the one spelling for the
  output format.

### Changed

- **Timeouts stop the work.** A timed-out node's Spark jobs are cancelled and its writes
  refused (it used to keep running and could write after the run failed); a node's
  `timeout` and `execution_timeout_seconds` are now enforced.
- Streaming nodes honour `dependencies`; an output's `filepath` is honoured; pipeline-level
  `inputs`/`outputs` are deprecated (never read); a node function receives
  `start_date`/`end_date` only if it declares them; `mode` defaults to `local`.
- Projects in the API are format-2 projects; `ducta template` writes commented YAML
  directly, and new projects no longer start with nine "Unknown key" warnings.
- Every `ducta` command starts about 0.3 s faster; node outputs are cached before the
  quality phase.

### Fixed

- **Quality**: checks on a misspelled column passed; a gate blocked runs on data it was
  configured to tolerate; a blocked gate showed as `❌ Unknown Error`; a declared
  `sanity_gate` was never consulted; checks decided correctly and then misreported it.
- **Runs and certificates**: a zero-row node was recorded as a success that wrote data;
  `gate_blocked` and `skipped` were lost; hybrid reported success for runs that started
  nothing and `ducta stream run` exited 0 when every node failed; a streaming node could
  not depend on a batch node; outputs without a write mode appended on every run;
  `versionAsOf: 0` read the latest version; every batch run opened a tracking run.
- **Config validation**: false all-clears and bogus "Unknown key" warnings, a one-character
  typo costing a JVM startup, and settings the engine read but the schema rejected
  (`checkpoints_base`, `mlops_path`, `streaming_*` …); a test now fails when the engine
  reads a setting the schema does not declare.
- **MLflow and models**: models were never logged unless three frameworks were installed;
  logging failures are errors (`settings.mlflow.required`); a persisted model with tracking
  off no longer overwrites the previous one; `model promote <name> 1.2.0` crashed.
- **Packaging and CI**: a wheel could ship without the web app; CI was red in three jobs.

## [0.1.1] - 2026-08-29

Ships the security fixes below to users of `0.1.0`. **It is not a pure patch release:** it
also carries behavioural changes (the per-environment certificate layout, the CORS
default) and new features.

### Security

- **A web page could drive the local API.** The defaults combined `cors_origins=["*"]`,
  credentials and `auth_enabled=false`, so any site a developer visited while running
  `ducta ui` could read the project path, write Python into it and run it. The default is
  now a loopback allow-list and the wildcard downgrade applies in every environment.
- **The same for WebSockets**: `/api/ws/terminal` and `/api/ws/logs/{id}` did not check
  `Origin`, so any site could open a shell. Both handshakes now validate it.
- **The SQL sanitizer lost four of its five layers when sqlglot was installed** (an
  `AttributeError` skipped the AST scan). Lexical and structural checks both run now, an
  unresolvable scan fails closed, and `sqlglot` is bounded `<31`.
- **Ingestion nodes built SQL by string concatenation, unsanitized**; identifiers are now
  matched against a pattern and every statement and declared `query` goes through the
  sanitizer. `UnityCatalogDDL.vacuum()` coerces its retention to `int`.
- **An empty `GIT_CLONE_ALLOWED_HOSTS` meant "clone from anywhere"** (SSRF); outside
  development it now defaults to the public forges.

### Changed

- **The CLI exits with a meaningful status code** (every command used to exit 0, failures
  included), and errors raised by the engine map to the right HTTP status.
- **A blocked quality gate no longer reports success**, and means the same in hybrid
  pipelines; `min_pass_rate` is less strict by default; execution priority decides
  execution order.
- The UI no longer keeps the access token in `localStorage`, destructive actions ask in
  the app's own dialog, and the three table screens share one implementation.
- **Relicensed from AGPL-3.0-or-later to Apache-2.0**, before the first public release.

### Fixed

- A run's status never reflected what its nodes did; a node that finished inside its
  budget could be recorded as a timeout; streaming was entirely non-functional and its
  conflict detection never reported a conflict; `ducta config validate --env` ignored the
  environment.
- Installs: `ducta[api]` produced an unimportable API, `ducta[all]` disabled local
  execution and `ducta[spark]` was impossible on Python 3.13 and could not convert pandas
  to Spark.
- The UI never loaded its typeface, two stylesheets were never imported, `npm run dev` did
  not proxy `/api`, and the file browser could never list a directory.

## [0.1.0] - 2026-07-22

First public release. Ducta is a unified data-pipeline framework that runs **batch,
streaming, ML and hybrid** pipelines from declarative configuration, with data quality,
MLOps and run governance built in.

- **Configuration** (`ducta.setting`): YAML/TOML/JSON/Python loading, Pydantic-validated
  schemas, `${VAR}` interpolation, environments (`base`/`dev`/`sandbox`/`staging`/`prod`,
  plus `sandbox_<developer>`), thread-safe Spark session management.
- **Engine** (`ducta.core`): batch, streaming, hybrid and ML executors, DAG dependency
  resolution with cycle detection and parallel execution with per-node timeouts, a preflight
  that fails fast, tamper-evident Run Certificates (SHA-256, optional HMAC), chain reuse.
- **Data I/O** (`ducta.gate`): Spark, Pandas and Polars I/O, a declarative JDBC gateway,
  SQL sanitization by AST parsing, in-memory node handoff, Unity Catalog.
- **Streaming** (`ducta.stream`): Structured Streaming with Kafka, Kinesis, Delta and file
  sources, lifecycle management with health monitoring and safe checkpoint paths.
- **Data quality** (`ducta.check`): pre-execution sanity checks and post-execution data
  quality checks, Quality Gates with weighted scoring (`block` / `warn` / `skip-downstream`),
  reusable profiles and custom `@register_check` extensions.
- **MLOps** (`ducta.mlrun`): experiment tracking and a versioned model registry with local
  and Databricks backends, fingerprinting, reproducible splitting, hyperparameter search and
  an optional MLflow bridge.
- **Interfaces**: the `ducta` CLI, a FastAPI REST + WebSocket server with optional JWT
  authentication, and a React web workspace.
- **Packaging**: a lean core with opt-in extras (`spark`, `api`, `database`, `mlops`,
  `monitoring`, `all`) and a multi-arch Docker image.

[Unreleased]: https://github.com/faustinolopezramos/ducta/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/faustinolopezramos/ducta/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/faustinolopezramos/ducta/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/faustinolopezramos/ducta/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/faustinolopezramos/ducta/releases/tag/v0.1.0
