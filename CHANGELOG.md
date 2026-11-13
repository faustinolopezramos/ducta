# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Ducta is **alpha**: APIs and configuration can still change between minor versions.
This file keeps what you need to upgrade (breaking changes, removals, security) and the
headline of everything else; `git log` has the detail.

## [Unreleased]

### Added

- **Model registry in the web UI**: each model is filed under the version in Production, with
  the latest version and the policy's refusal beside it; the promotion dialog checks the policy
  first (`GET /api/mlops/models/{name}/versions/{version}/promotion-check`) and says which nodes
  will serve the new version; each version links to the run (and certificate) that trained it;
  a model's *History* is its audit log (`GET /api/mlops/models/{name}/history`); the GC lists the
  versions it removes. A certificate says what started its run (`triggered_by`,
  `reproduction_of`) and which versions its training node registered; a run's page shows its
  retrain (`retrain` on the execution record).

- **Retraining on drift**: a scoring pipeline's `retrain: {run: train, when: [prediction_drift],
  cooldown: 1d}` makes Ducta run the training pipeline after a run in which one of those checks
  failed (also when the gate blocked it), at most once per `cooldown` (a refused or failed
  retrain counts), never from a reproduction, a sample run or a sweep/search trial. The training
  run's certificate says what started it (`triggered_by`, certificate schema 1.10); `ducta start`
  reports it and exits non-zero when the retrain did not succeed; `PipelineRunResult.retrain`
  (and `to_dict()`) carries it.
- **Promotion from the training node through the policy**: `persist_model(..., promote="production")`
  and `train_with_search(..., promote=…)` promote through `settings.mlops.promotion_policy`; a
  refused candidate stays in staging (`promotion_refused`), a sweep/search trial is registered
  and never promoted. The run certificate names the versions a node registered
  (`nodes[].ml.registered`).
- **`ducta model list` and `ducta model show NAME [--version N]`**: the registry's models,
  versions and stages, and one version's metrics, schema, library versions and lineage.
- **CI for ML projects**: `ml_basic` and `ml_scoring` write `.github/workflows/ml.yml` (check,
  node tests, train through the promotion gate, score, keep the certificates) and a `staging`
  environment. `ml_basic` ships a `hyperparams.yaml` so `--search` works as generated.
- A `--sweep` names its best run when it has a metric to rank by (`--search-metric` or the
  `hyperparams_config` objective); `experiment compare --all` shows Ducta's own parameters.
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

- **Data quality no longer skips its checks on a config or engine error** (review
  2026-11-12): a misspelled `severity:`, a gate that cannot be evaluated, an unknown
  profile or an output the checks cannot read now fail the node whatever `fail_fast`
  says. They used to be logged and the node finished as a success with nothing checked.
- **The quality baseline is saved from the first run that passes** (no ERROR failure,
  gate passed), not from the first run whatever its verdict: a blocked first load became
  the permanent reference and every good load after it read as an anomaly. A baseline or
  history that cannot be read is reported in `persistence_warnings` and not overwritten.
- **`data_quality.fail_fast` yields to a declared gate**, as `sanity_checks.fail_fast`
  already did: a `warn_only` gate was overruled by the first ERROR.
- **`auto_tune` keeps a `score_threshold` written on the node's or the global gate**; it
  only fills one in where none was chosen (it lowered a deliberate `0.95` to `0.475`).
- **`sanity_checks.input_index` outside the node's inputs is a config error**; it used to
  check input 0 instead.
- **Quality folders keep a dataset name's prefix**: `raw/orders` is stored as
  `raw__orders` (it shared `orders` with `gold/orders`). Reports stored under the old,
  colliding folder stay where they are.
- **A quality history keeps its last 1,000 runs**; older entries are dropped on append.
- **`ducta quality score` / `GET …/score`** answer `sanity_score: null` (and `dq_score:
  null`) when there is nothing to average, instead of a made-up `1.0`.

- **An overwrite no longer changes a Delta table's schema by itself**: `write.overwrite_schema`
  is now `false` by default, and an overwrite whose columns differ from the table's (one
  missing, added or retyped) fails and writes nothing. A missing column used to be kept as
  nulls with the run reporting success. Set `write: {overwrite_schema: true}` where the new
  schema is intended (Unity Catalog outputs too).
- **0 rows no longer empty a dataset**: a node that produced no rows fails instead of
  overwriting a dataset that holds data, unless the dataset sets `write: {allow_empty: true}`.
  A dataset that holds nothing yet is still written.
- **`certify verify --reproduce` (and the web's Reproduce) no longer rewrites the real
  datasets**: the reproduction writes under `<output>/<env>/.ducta/reproduce/<run_id>/` and
  runs over the dates the original run used. Certificates (schema 1.9) record them as
  `run_window`; a reproduction's certificate says `reproduction_of`.

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
- **Removed methods nothing called** (no caller in Ducta, its tests or docs):
  `QualityReportSerializer.to_pandas_dataframe`/`to_json_lines`,
  `GateResultSerializer.to_json_string`/`to_pandas_dataframe`,
  `MLOpsAutoConfigurator.get_logging_strategy`, `MLOpsException.with_context`,
  `ExperimentTracker.run_context`, `MLflowConfig.from_yaml`,
  `StorageBackendRegistry.list_available`, `StorageBackend.list_paths` (and its two
  implementations), `MetricValidator.validate_step` and
  `FrameworkValidator.add_supported_framework`.
- **A model registration that fails fails the training node.** `persist_model` (and so
  `train_with_search(name=…)`) used to warn and save a pickle under `./models`, and the node
  succeeded: the registry never got the model and serving kept the previous Production
  version. The local copy is now only for projects without a registry, and a model name
  follows the registry's rule (letters, digits, `_`, `-`, `.`) in both cases.
- **A search's cross-validated score is logged as `val_<metric>`** (`val_f1`,
  `val_roc_auc`), no longer under the bare objective name; `--sweep`/`--search` read
  `val_<metric>` first, then the bare name. With an objective that is also a held-out
  metric (`f1`, `accuracy`, `precision`, `recall`, `r2`), the held-out value used to win, so
  `--search` picked hyperparameters on the test set.
- **Dataset fingerprints bind each value to its column name** (algorithms
  `pandas-sha256/v3`, `xxhash64-multiset/v3`, `sha256-multiset/v4`, `spark-minhash/v4`):
  swapping the names of two same-typed columns left the fingerprint unchanged. Fingerprints
  in earlier certificates are reported as "not comparable" (algorithm differs), not as
  changed.

- **`settings.mlops.promotion_policy` is validated when the project loads**: a misspelled key
  (`min_detla`) or an unknown `compare_to` is an error; it used to be dropped and the gate ran
  without it. The `ml_scoring` template promotes through the policy instead of in node code,
  and its train run fails when the new model stays in staging (the drift reference is kept).
- `experiment compare` leaves out Ducta's own parameters (`_code_hash`,
  `_environment_snapshot`, the fingerprints) unless `--all`: one of them made rows 11,000
  characters wide.

### Security

- **A project can no longer read the server's secrets through an alert or a connection.**
  An alert's `url_env`/`webhook_env` named any environment variable, and a test alert's
  error quoted its value: whoever could edit the project's alerts (the `developer` role)
  read `JWT_SECRET_KEY` and could sign an admin's session. A connection's
  `<NAME>_USER`/`<NAME>_PASSWORD` were taken one by one from the environment or the
  project's `.env`: a connection named `ducta_admin` used the server's
  `DUCTA_ADMIN_PASSWORD` against a host of its choosing. The server's own secrets
  (`ducta.server_secrets`) are refused in both places, alert errors never quote a value,
  and a connection's user and password must come together, from the environment or from
  the `.env` (half in each is an error that says which). Runs' processes also lose the
  SMTP credentials and the Redis URLs.
- `PUT /api/git/config` refuses a name or e-mail with control characters (a line break
  could add a section to `.git/config`), whatever GitPython version is installed.
- **`certify verify --reproduce` empties only its own folder.** The run id it cleared
  `.ducta/reproduce/<id>` with came from the certificate's JSON, which an unsigned
  certificate does not protect: an id such as `/home/me` or `../../..` deleted that folder
  instead. An id that is not a plain name, or a folder outside `.ducta/reproduce`, is now
  refused before anything is deleted (the API's reproduce runs share the fix).
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
- **The `developer` role is documented for what it grants**: with `RUN_ISOLATION=thread`,
  pipelines run inside the API process, so code a developer runs can read `JWT_SECRET_KEY`
  (see "Runs in their own process" below). The server says which applies at startup when
  authentication is on (`docs/server_api.rst`, `SECURITY.md`).
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
- **Runs in their own process** (`RUN_ISOLATION=process`, the default once `AUTH_ENABLED=true`;
  `auto` keeps in-process runs for a personal `ducta ui`). A run's code can no longer read the
  server's memory — its settings, `JWT_SECRET_KEY` — and its environment carries none of
  `JWT_SECRET_KEY`, `DUCTA_ADMIN_PASSWORD`, `DATABASE_URL`; on Linux the server also closes
  `/proc/<pid>/environ` to it (`PR_SET_DUMPABLE`). Logs, node status, data breakpoints, the live
  streaming status, restarting a stream's node, certificates and error diagnosis work as before.
  Cancelling or a timeout now stops the run's process and its Spark JVM, which a thread could not;
  runs of different pipelines go in parallel up to `MAX_CONCURRENT_EXECUTIONS` (runs of one
  pipeline still wait for each other). Each run starts its own Spark. Not a sandbox: a run is the
  server's OS user and can read the files it can (see SECURITY.md).

### Fixed

- **A stream node with `quality:`, `quarantine:` or `merge` no longer writes a batch
  twice** (review 2026-11-12): written through `foreachBatch`, a parquet/JSON/CSV batch
  that Spark ran again after a crash (written, not yet committed) was appended a second
  time — 30 rows for 15 — where Spark's own file sink is exactly-once. Batches are now
  staged and published under a per-batch marker (`<sink>/_ducta_staging/`,
  `<sink>/_ducta_batches/`). A CSV quarantine is written with a header.
- **Stream quality that cannot run stops the query**: a misspelled `severity` (or a
  broken gate, an unknown profile) let every batch through unchecked.
- **A stream node's baseline is saved** from its first passing batch: it was held back
  with the reports and dropped 99 times in 100, so `anomaly_detection` and
  `drift_detection` had nothing to compare with. A local JSON history gets every batch.
- **Stream totals survive journal rotation** (`carried.json`): a run long enough to
  rotate `batches.jsonl` twice reported a fraction of its rows in its certificate and in
  the API. The newest 50 finished runs per pipeline are kept.
- **A hybrid run's stream phase is in its certificate and sends alerts**: its manager had
  no listener. An asynchronous hybrid run's certificate is now sealed when the stream
  phase ends (a run whose batch phase failed is sealed at once, as failed).

- **`ducta start --node` exits 4 when the node fails** (review 2026-11-12), as a whole run
  does: the node's exception reached the CLI raw and was reported as an unexpected error
  (exit 1). Ducta's own errors keep their codes (a lock is still 7).
- **The agent skill finds TOML and JSON projects** (skill 1.1.4): `check_env.py` looked for
  `ducta.yaml` only, so a project made with `ducta init --format toml|json` had no
  `project_root`; SKILL.md, its description and the AGENTS.md block now name every format.
  `check_env.py` also reports the `database` extra, and `api`/`ai` check `jwt` and
  `ruamel.yaml`. The skill's exit-code list names all of them, and its quality and
  Sentinel references describe the behaviour changes of this release.

- **Sentinel re-runs inside the server** (review 2026-11-12): the run-finished hook,
  the periodic pass and an incident's *Retry* call the execution manager from a worker
  thread, where it failed with "no running event loop" — no server-side re-run ever
  started. Worse, each attempt left a "pending" run by `sentinel` in the history and in
  the queue; at the same priority, five of them later took every concurrency slot and
  the server's next run waited forever. `ExecutionManager.execute_from_thread` hands the
  call to the event loop, and `execute` now refuses, before recording anything, to run
  off it.
- **Sentinel and Architect child runs** (`ducta ai sentinel watch`, `architect verify`)
  start Python with `-P`: with `-c` the project folder came first on `sys.path`, so a
  project file named like a standard module (`json.py`, `calendar.py`) broke the run
  before it began.
- **Slow runs the server started** open a `slow` incident: only a scan looked, and a
  scan skips the runs the server's hook already handled.
- **The CLI re-run's outcome** is the certificate of the run that began during the
  re-run, not the pipeline's newest one (a person's run right after it was read as
  Sentinel's); a locked re-run takes none.
- **Sentinel incidents** resolved or ignored more than 90 days ago move to
  `.ducta/ai/sentinel/incidents/archive/` (still readable by id): every run and pass
  read the whole folder, which only grew.

- **Quality checks and missing values** (review 2026-11-12): on Spark a single `NaN`
  made a column's `max()` NaN, so `range` and `prediction_contract` passed a `1e9` next
  to it; NaN is now left out as pandas leaves it out. On pandas a column gone entirely
  null had a NaN mean and passed `anomaly_detection`; it is now reported as not evaluated.
- **Quality report datasets on cloud storage**: `settings.quality.output` wrote
  `s3://bucket/q` reports to a local folder `s3:` (paths now keep their scheme).
- **`incremental_volume`** compares with the average of the runs that passed; blocked or
  failed loads dragged the norm down (300 rows against a usual 1,000 passed).
- **Python business rules** must answer `True`/`False`: a rule returning a number gave
  negative "violations" and passed; it is now a rule error.
- **`null_rate`** counts every column in one pass (30 columns were 62 Spark jobs, now 4).
- A storage error while saving the report of a fail-fast abort no longer replaces the
  check failure that stopped the node.

- **Cloud output paths** (review 2026-11-11): `s3a://`, `s3n://`, `abfs://`, `wasb(s)://` and
  `hdfs://` are cloud URIs everywhere (one list, `ducta.gate.constants.CLOUD_URI_PREFIXES`); a
  derived dataset path or a streaming checkpoint on them was written as a local folder named
  `s3a:`. With a cloud `paths.output`, run certificates, chain state, run locks and stream
  journals default to `.ducta/<env>/…` locally (they went to a local folder `s3:`), and a cloud
  `run_certificate_dir`/`chain.state_dir` set by hand is a preflight error. A cloud output with
  the default local run lock no longer fails at `ducta start`.
- **Credentials in run evidence**: a node error holding a password or a URL login is masked in
  the run certificate, the run result and on the terminal, as it already was in the log file
  (`ducta.redaction`); `spark.…secret.key <value>` listings are masked too.
- **`--node` honours `timeout_seconds`**, like a whole-pipeline run (it ran unbounded).
- **`anomaly_detection`** no longer skips a column collapsed to a constant; **`freshness`**
  fails on a timestamp more than an hour in the future.
- **`run_in_process` in a reproduction or sample run** reads what the run wrote, not the real
  upstream dataset.
- **Python `business_rules`** collect the data once, and refuse above `max_rows` (new optional
  parameter, default 5,000,000) instead of taking the driver down.
- A node returning a tuple or list gets a clear error (one DataFrame per node, written to each
  output).
- **`-q`** prints errors only (and one final line) on the classic log: banner, passing quality
  tables, schema and sections are gone.
- **`ducta model gc`** (and `POST /api/mlops/gc`) lists the certified runs whose model version
  it removes (`served_in`): `certify verify --reproduce` cannot pin it afterwards. What it
  deletes is unchanged.

- **The registry's audit log names who did it**: a promotion from the web UI was recorded as the
  server's operating-system user with no reason; it is now the signed-in user, and a forced
  promotion requires a reason. Deleting a version (also by `gc`) and a promotion the policy
  refused are now audit-logged too.
- **Deleting the version in Production from the web UI** asked to type the version and then
  always failed (the registry protects it); the button is now disabled with the way out.
- **A scoring run that retrained linked the training run's certificate** in the web UI: the
  training run left its own run id on the shared context. The scoring run's id is put back.

- **`run_in_process: true` nodes work**: the worker read the same flag and tried to start a
  worker of its own ("daemonic processes are not allowed to have children"), so every such node
  failed. Its evidence now reaches the run certificate (input/output fingerprints, code hash,
  quality results, `nodes[].ml`), so it can be reproduced and its failed checks trigger
  `retrain:`; a tracked run's worker registers and promotes in the run's registry instead of
  writing a local pickle; and in a `--reproduce` or a sample run the worker uses the scratch
  registry and the pinned model versions, as an in-process node does.
- **`persist_model(promote=…)` checks the stage before registering**: a misspelled one left a
  version registered and failed the node.
- **A sample run's nodes read the datasets the run wrote**, not the real ones: a downstream
  node read the real intermediate dataset (or was skipped when there was none). A single node
  of a sample run still reads its real upstream.
- **A node with several outputs checks they are all writable before writing any**; a write
  that still fails halfway is listed in the certificate's evidence gaps (`partial write`).
- **A server run from a source tree runs its runs' processes with the same Ducta**
  (`RUN_ISOLATION=process` started whatever Ducta the interpreter had installed, or none).

- **`PUT /api/nodes/{name}` accepts a node exactly as `GET` returned it**: the read side
  turns `input`/`output` into `inputs`/`outputs` lists for the UI, and saving that back
  was refused ("key 'inputs' is not a node setting Ducta reads"). A `quality` or
  `input_checks` block sent back with the same meaning now keeps the form it was written
  in (`empty_dataset: true`, checks listed inline) and its comments; before, it was
  rewritten in its long form (`checks: {empty_dataset: {}}`) and the comments were lost.
- **UI dev dependencies**: vitest 2 → 4.1.12 and scoped overrides for glob, minimatch and
  uuid (under Storybook and typescript-eslint); `npm audit` reports 0 vulnerabilities,
  dev tooling included.

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
- **A hybrid pipeline that does not validate says why**: the run failed with "Hybrid pipeline
  validation failed" alone; the error now lists every reason (a batch node waiting on a stream,
  incompatible formats, a missing checkpoint…), and the warnings are logged.
- **`quality.output.global_summary: true` writes the run's quality summary**: the switch was
  validated and then ignored. The summary goes next to the quality reports
  (`<quality>/global_summary/<pipeline>/<run_id>.json`), one file per run, instead of
  `./.quality/global_summary` in the working directory. A chain's next pipeline no longer
  lists the previous one's quality reports (in the summary or in the certificate).
- **The Databricks experiment store honours `append` when it falls back to its local cache**:
  an append replaced the cached rows with the new ones (`ignore` and `error` now apply too).
- **A temporal split keeps one instant on one side**: rows sharing the boundary's time were
  split between train and test on pandas (Spark already cut by value). Rows without a time
  (null, or not a time) now stop the split with their count instead of all going to test.
- **A mistyped `search_space` entry is an error**: `{min: 1, maximum: 10}` was searched over
  its key names, and a string over its letters. An entry is a list of values, a
  `{min, max[, step, log]}` range or a `depends_on` condition.
- **Bayesian search tells Optuna about every trial**, even when it proposes the same values
  twice (the first one stayed RUNNING in the study).
- **The API refuses a Production promotion when `mlops.promotion_policy` is invalid** (or names
  no metric), unless forced, as `ducta model promote` does; it used to promote without the
  gate. The Databricks experiment store says it ignores `workspace_url`/`token` (it
  authenticates through the Spark session), and a Spark ML model's class must come from
  `pyspark.ml` itself or a package below it.
- **The web app no longer sends a POST again after a client timeout**: a quality run, a
  git commit/push/pull, an AI job or a draft's apply that took over 30 seconds was sent up
  to three more times while the server was still running the first. Only reads are
  retried after a timeout; a 429 is still retried for any request.
- **`--reproduce` no longer changes the model registry**: reproducing a training run
  registered a new version and promoted it to production (and opened a tracking run). A
  reproduction's — and a sample run's — registry and tracker now go to a scratch store, and a
  serving node reads the real registry, at the version the reproduced run used (not today's
  production).
- `ducta check` no longer logs a made-up `dataset_size=10000` next to the split it validates.
- A random search no longer proposes the same values twice while new ones remain (with the
  templates' seed, two of six trials were repeats).
- **`WriteMode` is one class**, shared by `ducta.gate` and `ducta.setting`, and `str()` of a
  member is its value (`"merge"`). The two copies differed (a plain `Enum` and a `str` one), and
  a mode handed from one side to the other read as `WriteMode.MERGE`.

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
