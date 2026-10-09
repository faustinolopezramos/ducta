# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - Unreleased

Configuration format 2 (`ducta.yaml`, the catalog and `pipelines/`) replaces
format 1, which is no longer read, and `ducta template` writes the new format
directly.

### Security

- **No known vulnerabilities in the installed dependencies** (pip-audit on a clean
  `ducta[all]` install; it reported 54 entries — 28 distinct advisories — before):
  `mlflow` moves to `^3.15.0` (27 advisories, all fixed by 3.15.0 or not affecting
  3.16), `pyarrow` to `>=23.0.1,<25` (CVE-2026-25087, use-after-free in Arrow C++;
  `<25` because databricks-connect 14 requires it), and the dev-only `pytest` to
  `^9.0.3` (`pytest-cov` to `^7.0.0`). The CI's dependency audit is blocking again.
- **The API's deep preflight needs `pipeline.execute`**, not `pipeline.read`. It
  imports the project's modules, which runs their top-level code, so a read-only
  role could run project code through it.
- **A Git URL as a source needs `repository.write`** (`?source=`, `X-Source-Path`,
  `POST /api/workspace/select`). Any authenticated user could make the server
  clone a repository. The operator's `DUCTA_WORKSPACE` is not checked.
- **Model promotion and deletion have their own permissions**: `model.promote`, and
  `model.delete` for deleting a version and for gc (both developer). Before, they
  needed only the generic `execution.write`.
- **Testing an unsaved ingestion connection needs `ingestion.write`**: the server
  connects to whatever host and port the caller sends.
- A test walks every API route and fails if a route that writes is reachable by
  a viewer.

### Changed (breaking)

- **Saving from the web app or the API no longer commits.** Every write is still
  validated against every environment before it is kept, but committing is now the
  user's call — the web app's Changes panel, or git itself. The optimistic-concurrency
  token (still returned as `commit_sha`, sent back as `expected_sha` /
  `expected_commit_sha`) is now a hash of the file's content, so an uncommitted edit
  made by someone else since you read the file is a `409` too.

- **Quality reports of a pipeline run default to `<paths.output>/<env>/quality/`**, not
  the hidden `.quality/`, so they sit next to the data and can be browsed or shipped.
  A project whose environment already has a `.quality/` (and no `quality/`) keeps
  using it, so its baselines and score history carry over; rename it to adopt the new
  default. `settings.quality.output.base_path` still overrides both. `ducta quality
  run` on a bare file still writes to `<workspace>/.quality/_adhoc/`.

- **A declared train/test split is enforced.** A node bound to a split — its own
  `split:`, or the pipeline's for an `ml_stage: training`/`evaluation` node — that finishes
  without applying it (`ducta.mlrun.split_dataframe`/`kfold_splits` with its
  `ml_context`) now fails before its output is written; it used to log a warning.
  `settings.split_enforcement: warn` restores the warning. A pipeline `split` that no
  node is bound to apply, or a bound node whose function has no `ml_context` parameter,
  is reported by `ducta config validate`. Feature nodes under a pipeline split are no
  longer warned about.

- **MLflow 3.15 or later** (`mlops` extra). MLflow 3 refuses a local-folder tracking
  store unless `MLFLOW_ALLOW_FILE_STORE` is set; Ducta sets it when a project
  configures one (`tracking_uri: mlruns`, `file://...`) and warns, recommending
  `sqlite:///.../mlflow.db`. Models are logged with MLflow 3's `name=`.

- **A dataset's contract is `quality:`, not `checks:`.** The catalog now names the
  block the way nodes do. `checks:` on a catalog entry is an error that says to use
  `quality:`; rename the key (the block's contents are unchanged, and its checks can
  be listed directly beside `gate`, without a `checks:` level).

### Removed

- **The legacy certificate switches.** `enable_run_certificate` and
  `require_run_certificate` are gone from `settings`; `evidence_level`
  (`off | record | required | signed`) is the only way to choose how much evidence a
  run leaves. A project that still sets them gets the usual unknown-key error.
  The `Ducta_CERTIFICATE_KEY` spelling of the signing-key variable is no longer read;
  use `DUCTA_CERTIFICATE_KEY`.

### Changed

- **Web app UX pass.** A queued run is "Queued" everywhere (it was "Pending",
  "queued" and counted as "Running"), and one queued over 10 minutes is marked
  stuck. The header holds the workspace switcher (its name, not its path) and an
  account menu with Sign out; Certificates is in the rail and ⌘K. Page titles match
  the rail (Projects, Quality, Models, Git). On a pipeline the name is never
  truncated, the chain strip loses its scrollbar and hides when narrow, the
  inspector's rarer actions move into a "⋯" menu, and the code pane replaces the
  inspector instead of squeezing the canvas. The project map is readable (min zoom,
  short edge labels). Font sizes come from the type scale (11px minimum), overlays
  from a z-index scale, and the theme follows the system until one is picked.

### Added

- **The web app is laid out like a code editor**: explorer, canvas or editor,
  an inspector for the selected node or dataset (effective config per environment,
  data preview, quality, runs, tests, connection), a bottom panel for logs and
  problems, a command menu (⌘K / Ctrl+K) and one environment switcher for the whole
  app. The Python editor lints with Ruff (WebAssembly, in the browser) and, when the
  server finds one (`LSP_COMMAND`, or `basedpyright`/`pyright`/`pylsp` on the PATH),
  talks to a language server; a debugger attaches over DAP with breakpoints.
- **Format 2 grows, additively** (`version: 2` unchanged; ADR 0001 in `docs/adr/`):
  recognised `metadata` keys (`owner`, `tags`, `sla`, `pii`, `criticality`, `docs`);
  `alerts:` rules in `ducta.yaml` (`failure`, `quality_gate`, `sla_miss`, `slow`,
  `stale` → Slack, Teams, webhook, email); node templates (`templates/nodes/`,
  `use`/`with`) and subpipelines (`templates/pipelines/`, `use: pipeline:<name>`);
  and a `governance:` block (`protected_environments`, warnings for a missing owner or
  contract).
- **An `operator` role**: runs pipelines — including in protected environments, which
  take the new `pipeline.execute.protected` permission — and handles runs, but does
  not change projects or code. Developers can no longer run in a protected
  environment (`prod`, `production` by default).
- **API for the editor and inspector**: validate unsaved edits, edit a pipeline's
  source or apply canvas operations (with undo), extract a node template or a
  subpipeline, node effective config, environment comparison, dataset preview, column
  lineage for ingest nodes, quality drafts and failing rows, node tests and snapshot
  tests, staleness since the last success, run metrics, a failed run's diagnosis,
  comment threads (`.ducta/comments/`), alerts (`SLA_CHECK_MINUTES` for an SLA watch)
  and governance. See `docs/server_api.rst`.

- **Serving: `ml_stage: serving` scores with a registered model.** A node names its
  model — `model: {name: churn, stage: production}`, an exact `version`, or an MLflow
  `source: mlflow, uri: models:/churn@champion` — and receives it loaded as
  `ml_context.model`, with `ml_context.model_ref` saying which one it is. A stage is
  resolved once per run, so every node in the run scores with the same version even
  if a promotion lands mid-run. Without `run`, the built-in scorer
  (`ducta.mlrun.serving:predict`) applies the model to the node's single input and
  adds `output_col` (`method`: `predict`, `predict_proba`, `decision_function`,
  `score_samples`), on pandas or Spark. A pickle/joblib model loads only with
  `trust_artifact: true`. `ducta config validate` checks the model resolves.
  Before, `serving` was accepted and did nothing.
- **The certificate names the model each serving node scored with** (schema `1.6`):
  `nodes[].ml.model` records the source, name, the version the run pinned, the stage
  it was resolved from and the artifact's SHA-256. `ducta certify diff` reports a
  model change, and two runs that scored with different models are not equivalent.
- **The model registry records each artifact's SHA-256 at registration**, and serving
  refuses a copy whose hash no longer matches.
- **A streaming node can score with a model**: `stream.model` takes the same block.
  The model is resolved when the query starts and kept for its lifetime (a restart
  resolves it again); without a `transform` the built-in scorer applies it to each
  micro-batch, and a transform with an `ml_context` parameter receives it. The
  pipeline status lists each query's model under `served_models`.
- **`output_type`** on a model sets the prediction column's Spark type (`double`,
  `long`, `string`, `boolean`) instead of inferring it from one row; a stream, which
  cannot be sampled, defaults to `double`.
- **Checks on a model's output**: `prediction_contract` (every row scored, within
  `min`/`max`), `prediction_rate` (the share of rows flagged stays within bounds)
  and `prediction_drift` (PSI or KS of the scores against a `reference` dataset,
  such as the validation scores the model was promoted on).
- **`split_dataframe` splits a Spark DataFrame** without collecting it: `random` and
  `group` by a content hash (independent of partitioning, groups never span
  partitions), `stratified` with exact per-class shares, `temporal` at the time
  column's quantiles. `kfold_splits` still needs pandas.
- **Spark ML models in the registry and the serving node** (`framework:
  spark-mllib`, the directory `model.save` writes): validated by layout, loaded
  without unpickling, scored with `transform`.
- **`ducta[boost]`** installs XGBoost and LightGBM (also in `ducta[all]`).
- **The API and UI show what serves what.** `GET /api/mlops/models` lists, per
  model, the project's nodes that serve it and the stage or version each asks for
  (`served_by`); the registry tab shows them. A version carries its framework,
  features, hyperparameters and artifact hash, shown in the versions table.
  `GET .../ml-plan` adds `model_resolution` to a serving node — the version its
  stage names right now, or why there is none — and the node's ML panel shows it.
- **`GET /api/quality/checks` describes each check** (description, default
  severity, parameters as JSON Schema), and the run-checks builder uses it: the
  check's description, its parameters offered as you type, a value hint per
  parameter (`psi | ks`, `number 0–1`) and the check's own default severity. It
  replaces a hard-coded hint list that named parameters some checks do not take
  (`row_count: min_rows`).
- **Live streaming status.** `GET /api/executions/{id}/streaming` reports a running
  streaming or hybrid execution: per pipeline its status, uptime and active/failed
  query counts; per node its query's state, last batch, input and processed rows
  per second, trigger time, the model it scores with and any error. A pipeline
  with one failed node and others still streaming is shown, not hidden. The
  execution drawer and the pipeline page's log panel show it, refreshed every 5
  seconds while the run lasts.
- **`ml_scoring` template**: train and promote a model, then score new data with it
  through a code-free serving node and prediction checks against the validation
  scores. `ducta certify diff` between two score runs shows a model change.
- **The UI follows the user's permissions.** `GET /api/auth/me` now returns
  `permissions` (`["*"]` for an admin). The UI hides what a role cannot do (create
  or delete projects) and disables, with a tooltip naming the permission, what it
  cannot run: run a pipeline or node, run checks, edit code, Git writes, schedules,
  model promotion/deletion, ingestion connections. With auth off nothing changes.
- **ML evidence in the certificate view**: an "ML" panel per ML node shows its
  stage, the split and where it was declared, model version, hyperparameters, and
  whether the split was *applied*, *not applied* (in red, with a warning, when the
  node was bound to apply it) or *not required*.
- **`GET /api/projects/{id}/pipelines/{name}/ml-plan?env=`** (`pipeline.read`)
  answers what `ducta config show --ml` answers. The pipeline view's node panel
  shows it: stage, split and its origin, whether the node must apply it (and
  whether the project fails or warns if not), merged hyperparameters and version.
- **`ducta config show --ml`**: what each ML node will be given — its split and where it
  was declared, whether it must apply it, its merged hyperparameters and model version.

- **`ducta init project`**: creates a project in the recommended layout
  (`--type batch|ml|streaming|hybrid`, `--format yaml|toml|json`, `--layout
  split|single`).
- **A catalog split by layer**: `catalog/<layer>.yaml` (any depth, any format)
  instead of one `catalog.yaml`. A dataset declared twice, or `catalog.yaml` next to
  `catalog/`, is an error naming the files; errors and `config explain` cite the
  real file and line. The API writes an edited dataset back to its own file.
- **Quality profiles in `quality/profiles.yaml`**, merged into
  `settings.quality.profiles` before environments apply; a profile defined in both
  places is an error. `profiles.json` joins the editor schemas.
- **Conventions** in the configuration guide: names for datasets, pipelines and
  nodes, one format per project, and the recommended layout.
- **TOML and JSON project files.** `ducta.toml` / `ducta.json`, `catalog.*`
  and `pipelines/*.*` are read as `ducta.yaml` is, and errors name the file and
  line in every format. `ducta template --format toml|json` writes a template in
  either, and `ducta config convert` rewrites a project.
- **`defaults`** in `ducta.yaml` (project) and in a pipeline file: values every
  dataset (`defaults.catalog`, by glob) and node (`defaults.node`,
  `defaults.stream`) gets unless it sets its own.
- **Pipeline templates**: `extends: templates/name` with `params:` and
  `${params.x}` placeholders, under the file's own keys.
- **Inline checks**: a `quality` or `checks` block can list its checks directly
  beside `gate`, without the `checks:` level.
- **Typed check parameters.** `ducta config validate` rejects an unknown
  parameter, a value of the wrong type or range, and a near miss of a built-in
  check's name, with file and line; the editor schema offers every check's
  parameters. Custom checks opt in with `CONFIG_SCHEMA`.
- **`ducta config show | explain | diff | convert`**: the project as it
  resolves for an environment, where one value comes from, what differs between
  two environments, and the files in another format.
- **`ml_basic` and `hybrid_basic` templates**: a churn model with a declarative
  split, versioned hyperparameters and a baseline gate; and one `type: hybrid`
  pipeline whose batch node feeds a stream-static join.
- Stream triggers accept an interval (`trigger: 10s`, `5 minutes`) or
  `available_now` / `once`.

### Fixed

- **A fresh execution database no longer stops the server from starting.** No
  `alembic.ini` ships (or exists in the repo), so startup migrations were skipped
  and the first query failed with "no such table: users". Alembic is now configured
  in code; a database created while they were skipped is stamped at head, not
  rebuilt.
- **Web app: what you see is in the environment the header shows.** The overview,
  data previews, node tests, node runs and the dataset page silently showed `dev`
  while `base` was selected; Quality and Models had their own environment pickers
  that ignored it.
- **Web app:** opening a file by its URL raised a false "is not a file in this
  workspace" error; an 8-character run id (as the tables show it) said "No such
  run" and stacked four identical error toasts; a finished run's logs said "Idle";
  the pipeline's logs bar said "No runs yet" for a pipeline with runs.

- **Output checks that compare with another dataset never got it inside a run.**
  `referential_integrity` and `dataset_completeness` with a `reference_dataset`
  always failed with "Reference dataset ... not available": the runner never passed
  the dataset to the checks. It is now read (or reused, when the node already read
  it) and recorded among the run's inputs, and a reference missing from the catalog
  is reported by `ducta config validate`.
- **A streaming run started from the API could read and write in the wrong
  directory.** Paths a stream node declares inline (`stream.input.options.path`,
  `output.path`, `checkpoint_location`) stayed relative, and Spark resolves those
  against the directory its JVM started in — the first project the server ran.
  They are now made absolute against the run's project, as catalog paths were.
- **The model registry's versions table showed every version as Staging, with no
  metrics**: it read `stage`/`metrics` under a `metadata` key the API never sends.
- **A scikit-learn model saved with joblib could not be registered with
  validation**: the validator opened it with `pickle.load`, which cannot read
  joblib's format.
- **`anomaly_detection` is documented as what it is**: a check on a column's mean
  against the stored baseline, not a per-row anomaly flag.
- **The `viewer` role could not list projects**: it lacked `project.read`.
- **The WebSocket rate limiter could reuse another configuration's limiter** when
  a settings object's `id()` was recycled. It now matches the settings object
  itself.
- **A node's own `split` and `model_version` never reached its `ml_context`.**
  `Context.get_node_ml_config` dropped them, so the pipeline's split (or none) was
  used without a word. Both now reach the node, over the pipeline's; a run's
  `--hyperparams`/`--model-version` override both (a node's hyperparams used to override
  the CLI's). Running one node (`ducta start -n`) now gets the same per-node ML
  context as a full run — it used to skip the node's hyperparams too.
- **The run certificate now proves the split.** Each ML node's entry has an `ml` block:
  the split it was given, where it was declared, whether it was bound to apply it,
  whether it did, its model version and hyperparameters. It used to record nothing
  about whether a split was applied.
- **ML configuration typos are errors.** An unknown key in a `split`
  (`stratify_column`) was ignored and an unknown `ml_stage` (`trainning`) accepted,
  quietly freeing the node from its split; both are errors with file and line now. A
  node's `split` is validated like the pipeline's, and the preflight's pipeline split
  validation — which read the split from a view that drops it, so never ran — runs.
- **MLflow logging failures are errors**, not warnings; with `settings.mlflow.required:
  true` (or `mlops_required: true`) they fail the node.
- `ml_stage` read from a validated config came back as `"MLStage.TRAINING"` instead of
  `"training"`.

- **Models were never logged to MLflow** unless TensorFlow, PyTorch and XGBoost were
  all installed. The flavor table touched `mlflow.tensorflow` and friends up front,
  which import their framework; the resulting `ModuleNotFoundError` was caught and
  logged as a warning, so the run succeeded without its model. Only the flavor in
  use is loaded now, and the tests read the model back instead of trusting that no
  error surfaced.

- **Mistakes the validation let through, and errors that named the wrong place.**
  - `ducta config validate` (and `start --validate-only`) now rejects an `inputs` key
    that is not a parameter of the node's function, with the parameters listed and a
    suggestion. It used to pass and fail only when the node ran, after the nodes
    before it had written their output.
  - A dependency cycle between nodes (through `after` or the data they read and
    write) or between pipelines is an error when the project loads, not only in the
    CLI's preflight, so the API and `ducta.load_project` catch it too.
  - An error in an `environments.<env>` override is reported at its line in
    `ducta.yaml`, not at the pipeline file whose key it addressed; a dotted override
    naming a node, pipeline or dataset that does not exist says so and suggests the
    nearest name.
  - Loading a project for execution no longer shows the engine's raw schema dump: its
    errors are mapped back to `file:line`, and a pipeline without nodes says so.
- **Template placeholders work in keys**, so one template can name its nodes and
  datasets per copy (`train_${params.target}`). Node names are unique across the
  project, so a template whose nodes had fixed names could only be used once. Two keys
  that become the same name, or a list used inside a name, are errors.

- **Stream nodes ignored `checkpoint_location`, `trigger`, `output_mode` and
  `query_name` written beside `input`.** The engine reads them from the node's
  `streaming:` block only, and the loader accepted the flat keys and dropped them
  silently. `stream:` is now a closed schema: those keys, and the same keys under
  `output:`, are errors that say they belong in `streaming:`, and a typo in
  `input`, `output` or `streaming` is an error with a suggestion.
- `ducta certify verify` looked for the signing key in `global_config.yaml`
  only, so a `certificate_signing_key` in `ducta.yaml` was never found.

### Removed

- **`ducta config migrate`** and everything that read configuration format 1
  (`environment.yaml` + `config/*`): `ducta.setting.project_migrate`, the
  format-1 detection in the CLI and the API, and the upgrade guide. A project
  still in format 1 (Ducta 0.1.x) can be converted with `ducta config migrate`
  from commit `7696708`, the last one that has it.

### Changed

- **`ducta template` writes `ducta.yaml`, `catalog.yaml` and `pipelines/*.yaml`
  itself**, as commented YAML, instead of rendering the old layout and
  converting it. The generated files explain each non-obvious key, use
  `inputs: {parameter: dataset}`, and ship real `environments:` overrides
  (`dev` runs serially with debug logging, `prod` widens `max_parallel_nodes`).
  The scaffold is validated against the project schema and compiled in every
  environment by the test suite.
- `ducta.setting.project_decompile` holds what the API's project store still
  uses from the old module: `decompile`, `canonical` and `write_schemas`.


### Removed

- **Loading configuration format 1** (`environment.yaml` + `config/*`) in the
  CLI, the API and the web app, with every alternative layout it accepted
  (single-file bundle, directory convention, two-file quickstart) and
  **layered projects** (`ducta.yaml` with `layers:`). A project still in that
  layout stops with exit code 2 and the command that converts it. `migrate`
  refuses layered projects with the instruction to convert each layer.
- `ducta.setting`: `ContextLoader`, `FlexibleConfigResolver`,
  `LayeredProjectDetector` and the layered helpers; `ducta.console`:
  `ConfigDiscovery`, `AppConfigManager`, `load_config_file`,
  `EnvironmentConfigValidator`, `ConfigCache`.
- CLI: `config list-configs`, `config clear-cache`, `--layer-name`,
  `--use-case`, `--config-type`, `--interactive`, and `ducta template
  --format` / `--legacy-config` (templates are always the current format).
- API: `GET /projects/{id}/config/format`, `POST /projects/{id}/config/migrate`
  and the migration banner in the web app; `config_format` in
  `POST /templates/generate`; `PipelineRepository`.

### Changed

- **Projects in the API are format-2 projects.** A workspace is one project or
  `projects/<id>/` projects; a project's description, variables and timestamps
  live in its `ducta.yaml` (`description`, `metadata`). Creating a project
  writes a valid, empty project; importing one requires it to be in place.
- **The run window is passed only to functions that declare it.** A node
  function receives `start_date`/`end_date` only if it has those parameters
  (or `**kwargs`); `def clean(orders): ...` used to fail with "unexpected
  keyword argument 'start_date'", and preflight demanded the parameters of
  every function in a pipeline that required dates.
- **`ducta quality validate-config --node N [--env E]`** checks the node as the
  project configures it in that environment, including dataset contracts and
  custom checks from `quality.extensions`; `POST /quality/validate-config`
  takes `{node_name, env}`. An unknown profile is an error, as it is at run
  time. (It read a format-1 `nodes` file, and was broken by the removal.)
- `ducta stream run|status|stop`: `--config` is optional — the project
  containing the current directory is used.
- `ducta config validate` exits 2 (configuration error), like `ducta start`,
  when the project does not load.
- `mode` defaults to `local` when `settings` omits it (it was required at run
  time but not by the schema).
- Unknown keys in pipeline and dataset definitions are reported as
  `unknown key 'timout' — did you mean 'timeout_seconds'?` instead of
  pydantic's "Extra inputs are not permitted".

### Added

- `ducta.load_project(path=None, env=None)`: the `Context` of the project
  containing `path`, found like the CLI finds it.
- Settings the engine already read but the schema rejected, so no project could
  set them: `checkpoints_base`, `streaming_node_start_retries`,
  `streaming_node_start_retry_delay_seconds`,
  `streaming_node_start_parallelism`, `streaming_status_cache_ttl_seconds`,
  `streaming_disable_backpressure_defaults`, `streaming_shuffle_partitions`,
  `streaming_adaptive_base_interval`, `streaming_adaptive_max_interval_seconds`,
  `mlops_path`, `mlops_storage_path`, `model_registry_path`. A test now fails
  when the engine reads a setting the schema does not declare.

### Fixed

- **Outputs without a write mode appended on every run.** The Context
  validates the engine documents with `OutputSchema`, whose `write_mode`
  defaulted to `append` and was written back into the document — so every
  format-2 dataset without `write:` appended on each run, and re-running a
  pipeline duplicated its data. The writer, the format-2 schema and the docs
  all state `overwrite` as the default; it now is. `ducta config migrate`
  writes `write: {mode: append}` for format-1 outputs that set no mode (they
  did append), so migrated projects keep their behaviour. Found migrating the
  demo projects: a second run doubled a Silver table.
- **Preflight contracts read the whole input.** Input checks before a run
  loaded inputs without the run's dates, so an `incremental` dataset was read
  and fingerprinted in full before every run.
- **Terminating streams read empty sources.** With `once`/`available_now`, a
  stream node started as soon as the node it reads from *started*, found
  nothing yet and stopped: an `available_now` bronze → silver backfill wrote
  nothing to silver. Dependants of a terminating node now wait for it to end.
- `PUT /api/configs/{env}/{name}` passed an argument the service does not take
  and answered 500 on every call.
- The integration tests ran the CLI from site-packages instead of the checkout,
  and without propagating its exit code — so their `returncode == 0` checks
  could not fail.
- A UI test leaked `DATABASE_URL` into later tests.

### Documentation

- Rewritten for the current format: configuration reference (settings,
  datasets, nodes, quality, environments, variables and secrets, upgrading from
  format 1), CLI reference with exit codes, quality, streaming, best practices,
  Databricks, MLOps, the REST API overview, and the tutorials (basic examples,
  batch ETL, streaming, MLOps, Airflow, certificates). The tutorials' projects
  were run as written. Corrections along the way: `${DB_PASSWORD}` is refused
  by design (credentials come from the environment or `.env` for database
  connections), `$VAR` / `$VAR|default` were never supported, a node's several
  `outputs` each receive the same DataFrame, and `on_missing_input` defaults to
  `skip`.
- Every YAML example in the docs and module READMEs that names its file is
  validated against the schema by the test suite, and the configuration
  guide's examples must form one valid project in every environment they
  override.


### Added

- **Configuration format 2.** A project is `ducta.yaml` (project, `paths`,
  `settings`, `environments`), `catalog.yaml` (every dataset once — read,
  written, or both) and one `pipelines/<name>.yaml` per pipeline with its
  nodes. It replaces 15 files for the medallion scaffold with 3. Unknown keys
  are errors reported with file, line and a suggestion; every problem is
  reported at once. Environments are deep-merged overrides of the whole project
  (settings, paths, catalog entries, pipelines), with dotted keys that resolve
  dataset names containing dots. Node kinds (`transform`, `ingest`, `stream`)
  each accept only their own keys; ordering is inferred from the datasets
  (`after:` otherwise). The format compiles to the same five documents the
  engine always read, so the engine, preflight and certificates are unchanged.
  JSON Schemas for editor autocompletion: `ducta config schema`.
- **Dataset contracts.** `checks` on a catalog entry are validated wherever a
  node reads the dataset — once per run, with the same verdict for every
  consumer — and recorded in the certificate as `phase: contract`. The engine's
  `sanity_checks` gained `inputs: {dataset: {...}}`: it used to validate only
  one input, chosen by `input_index`.
- **`ducta config migrate`** (`--check`, `--out DIR`, `--write`). Reads every
  environment of a format-1 project in any of its layouts, converts it, and
  compiles the result back to prove it configures the engine identically in
  each environment before writing; anything format 2 cannot express aborts
  with the reason. Measured: the migrated template produces byte-identical
  outputs (`content_hash`) to the original.
- **API and web app on format 2.** Same endpoints and payloads; edits are
  translated to format 2, written in round-trip mode (comments and key order
  survive — `ruamel.yaml`, in the `api` extra), validated for every
  environment before the commit, and rolled back on rejection. New
  `GET /projects/{id}/config/format` and `POST /projects/{id}/config/migrate`
  (dry run by default, with a preview of every file); the project page offers
  the migration. Creating a node takes `?pipeline=` in a format-2 project.
- **Templates generate format 2**; `ducta template --legacy-config` keeps
  format 1 (so does a non-YAML `--format`).

- **Run lock: one writer per output dataset.** A run locks every output it
  will write before reading any data. An overlapping run on any of those
  outputs — an orchestrator retry, a duplicated backfill, another pipeline
  writing the same table — stops with `PipelineLockedError` (exit code 7),
  naming the holder. `run_lock.backend: local` (default) is an OS lock released
  automatically if the holder dies; `storage` is a renewed lease on a shared
  filesystem or S3 (conditional writes) for multi-host deployments. Measured:
  two concurrent `ducta start` of the template pipeline → exit 0 and exit 7,
  one certificate.
- **`write_mode: merge` — upsert into Delta by key.** `merge.keys`,
  `when_matched` (update all / some columns / ignore), `when_not_matched`,
  `delete_when` for CDC, optional schema evolution. Null-safe key matching
  makes a re-run of the same batch idempotent; duplicate keys in the batch fail
  before the merge with the offending keys. Commit metrics land in the run
  certificate. The schema already accepted `merge`, but no writer implemented
  it — such a configuration validated and then failed at write time.
- **`incremental: {column: …}` on inputs** — read and fingerprint only the
  run's date window, pushed down to the source.
- **Local sessions enable Delta Lake automatically** when a dataset uses
  `format: delta`, with the jar matching the installed PySpark
  (`global_config.delta_package` to override). New extra: `ducta[delta]`.
- **`evidence_level` — the project chooses how much evidence a run must
  leave.** `off` (no certificate), `record` (default, unchanged behaviour),
  `required` (a run that cannot write its certificate fails), `signed`
  (required + HMAC-signed; preflight fails before the run when no key is
  configured). `ducta template --evidence-level …` writes the choice into a
  new project. The level is recorded inside the certificate (schema `1.5`), so
  `certify verify` holds a `signed` certificate to it: unsigned fails, and
  without the key it reports integrity only and exits non-zero. The legacy
  `enable_run_certificate` / `require_run_certificate` keys still work; one
  that contradicts an explicit `evidence_level`, or an unknown level, is a
  preflight error — an unknown level never falls back to a weaker one.

### Changed

- **Streaming nodes honour `dependencies`**, like every other node; only
  `depends_on` was read, so a streaming node declaring `dependencies:` lost its
  ordering. The streaming template now uses `dependencies`.
- **An output's `filepath` is honoured.** It was documented and then ignored:
  every output went to the path derived from its three-part key, which is why
  keys had to have exactly three parts. A key with an explicit `filepath` may
  now be anything; preflight warns when a declared `filepath` moves an output
  away from where it used to be written.
- **A node's `timeout` is enforced** — a declared, validated key nothing read.
- **Pipeline-level `inputs`/`outputs` are deprecated** (never read); preflight
  says so and the templates no longer write them.
- **Environments in the format-1 scaffold override global settings only**;
  the three identical copies of each catalog are gone.
- **Timeouts stop the work.** A timed-out node's Spark jobs are cancelled on
  the cluster (per-run, per-node job tags) and its writes are refused; before,
  its thread kept running and could still write after the run was reported
  failed. `run_in_process` nodes now run one process each and are terminated
  on timeout. `execution_timeout_seconds` is now enforced for the whole run —
  it was only a polling cap. Measured: a node with ~16 min of Spark work and a
  15 s timeout ends the run in 20 s with nothing written.
- **`fingerprint_mode` defaults to `auto`: evidence at batch cost.** Delta
  inputs are identified by commit version (no scan); windowed inputs are hashed
  over the window; other inputs in full up to `fingerprint_exact_max_bytes`
  (10 GiB), sampled above; outputs over the written batch. `exact` no longer
  pays a second full scan for a separate `count()`. Measured on 20M rows:
  0.97 s → 0.09 s (window) / 0.10 s (Delta). Delta fingerprints
  (`delta-version/v1`) are not comparable with earlier `exact` ones — the
  diff reports "not comparable", not a change.
- **`certify verify --reproduce` pins Delta inputs** to the versions the
  certificate recorded.
- **`certify verify` says what it proved.** A hash match on an unsigned
  certificate — or a signed one checked without the key — used to print
  "hash matches — untampered", although the hash carries no secret and anyone
  who edits a field can recompute it. Results now carry a `level`
  (`integrity` | `authenticated`) in the CLI, both verify endpoints and the web
  app; "untampered" is reserved for a checked signature.
- **The signing key's environment variable is `DUCTA_CERTIFICATE_KEY`.** The
  mixed-case `Ducta_CERTIFICATE_KEY` is still read as a fallback.
- **New projects no longer start with nine "Unknown key" warnings.** The
  templates wrote keys Ducta never reads: descriptive ones (`version`,
  `template_type`, `architecture`, `created_at`, `layers`) now live under a
  `metadata:` block; `spark_master`, `max_retries` and `default_date` are gone,
  because editing them changed nothing (retries are per node via `retry:`, and
  the local session always uses `local[*]`).

### Fixed

- **The README quickstart used a module the importer rejects** (`module:
  "nodes"` is outside the allowed prefixes); it now uses `pipelines.sales`.
- **`versionAsOf: 0` read the latest version.** `DeltaReader` used
  `config.get("versionAsOf") or …`, and version 0 is falsy: pinning a read to a
  table's first commit silently read the newest one.
- **Keys Ducta reads were reported as "Unknown key … Ducta does not read it".**
  `fail_on_error`, `require_run_certificate`, `certificate_signing_key`,
  `max_streaming_pipelines`, `node_timeout_seconds`, `preflight_enabled`,
  `strict_module_import` and others were read by `CoreSettings` or the output
  manager but missing from `GlobalConfigSchema`. They are declared now (with
  `None` defaults, so the validated dump never injects a value the user did
  not write — the same trap as `min_pass_rate` below, which also made
  `enable_run_certificate` arrive as `true` whether or not it was set), and a
  test keeps the schema in step with `CoreSettings`.
- **A check on a misspelled column passed.** `null_rate` caught the lookup
  error for each column, logged it, and reported "All checked columns within
  null rate threshold" having checked nothing — so `columns: [categroy]` on a
  node let data with nulls through its gate. `drift_detection`,
  `anomaly_detection` and `statistical` had the same shape one step removed:
  they failed only when *zero* columns were evaluated, so one good column hid a
  typo or an evaluation error in another. A column named explicitly in a check
  that is not in the dataset now fails the check (`details.missing_columns`),
  and a column that exists but could not be evaluated fails it as inconclusive
  (`details._column_errors`). Columns skipped by design — too few categories,
  no baseline entry, too few samples — are still skipped, not failed.
- **A quality gate blocked runs on data it was configured to tolerate.**
  `QualityGateSchema.min_pass_rate` defaulted to `1.0` while
  `QualityGateEvaluator` reads the same key with a default of `0.0` (rule off) —
  and `model_dump(exclude_none=True)` keeps a default, so every node declaring a
  `quality_gate` had `min_pass_rate: 1.0` delivered to the evaluator as though
  the user had typed it. The pass rate counts every failed check regardless of
  severity, so **any** failing check blocked the node, contradicting the
  `max_warnings: -1` sitting next to it. Measured on `medallion_basic`, with one
  check set to `severity: warning`:

  ```
  node_id=transform status=gate_blocked
    Quality gate 'quality_gate' blocked dataset 'transform':
    Pass rate 0.6667 below min_pass_rate 1.0
  skipping 1 descendant(s): ['load']     exit 4
  ```

  The same YAML evaluated outside the schema returned `PASS`, so a gate meant
  different things depending on how the config had been loaded. The schema
  default is now `0.0`, matching the evaluator. An ERROR still blocks — verified
  — and an explicit `min_pass_rate` still applies.

  Both defaults had tests (`tests/check/test_gate.py::TestDefaultsAreIndependent`
  and `tests/setting/test_schemas.py::test_quality_gate_defaults`) and both
  passed, because neither crossed the seam between them.
  `tests/check/test_gate_schema_seam.py` now walks the whole path: YAML →
  `NodeSchema` → dump → evaluator.

- **`ducta config pipeline-info` crashed on every project.**
  `Context.pipelines` is the *expanded* view, where each node name is replaced
  by that node's whole config dict. `get_pipeline_info` passed it straight
  through, so the CLI's `", ".join(info["nodes"])` raised
  `TypeError: sequence item 0: expected str instance, dict found`, and
  `config list-pipelines --format json` emitted entire node configs where names
  belonged. `description` was dropped by the same expansion, so every caller
  reported an empty one.

  `get_pipeline_info` now returns node *names* via the existing
  `extract_pipeline_nodes`, and the expansion carries `description` through.
  Three callers had grown their own
  `n if isinstance(n, str) else n.get("name")` coercion to work around this;
  those are gone. A fourth had not, and `--node` membership was therefore tested
  against dicts — so `ducta start --node <name>` warned "may not exist" for every
  node that did exist.

- **A streaming node could not depend on a batch node in a hybrid pipeline.**
  Batch and ML nodes declare predecessors with `dependencies`; streaming nodes
  use `depends_on`, and only one key was read in each place. In a hybrid
  pipeline's streaming phase only the streaming node names are handed to the
  manager, so `depends_on: [<a batch node>]` was rejected as an undefined node —
  by the config validator, by the topological sort *and* by the wave loop. The
  sort raises, so the whole streaming phase failed rather than one node being
  deferred.

  `get_node_dependencies` now returns the union of both keys, so dependency
  inference and cross-type validation see every edge. `start_pipeline` accepts
  `satisfied_dependencies` for predecessors completed outside the sub-pipeline,
  which the hybrid executor fills with its completed batch nodes. A standalone
  streaming pipeline still rejects a dependency nobody produces.

- **Hybrid reported success for runs that started nothing.**
  `_execute_streaming_phase` marked every node completed the moment
  `start_pipeline` returned an execution id — but that call is asynchronous, and
  the id means only that the startup work was queued. Combined with the
  dependency bug above, a hybrid pipeline whose streaming node depended on a
  batch node reported a clean success while doing nothing at all.

  `StreamingPipelineManager` gained `wait_for_pipeline_started()`, signalled once
  every node has started, been skipped, or failed to start — a different moment
  from the terminal state `wait_for_pipeline_done()` tracks, which for a
  long-running trigger never arrives. Hybrid now waits for it and mirrors the
  real per-node outcome; a streaming phase that started no queries is a failure.

- **`ducta stream run` exited 0 when every node failed to start.**
  It printed the execution id and returned `SUCCESS` immediately after the
  asynchronous submit, so no script wrapping `ducta` could tell a running
  pipeline from one that had failed outright. It now waits for the startup pass,
  logs each skipped or failed node with its reason, and returns
  `EXECUTION_ERROR` when nothing started.

- **Every batch run opened an experiment-tracking run.**
  `_start_mlops_integration` consulted only `settings.mlops_enabled` and never
  asked whether the pipeline contained any ML. The detection for exactly this —
  `MLOpsAutoConfigurator.should_init_mlops_for_pipeline` — existed but sat on a
  dead path: its only caller was a `BaseExecutor.mlops_context` property no
  production code read. On the `medallion_basic` scaffold, which has no ML node,
  every run created `data/<env>/experiment_tracking/` and logged:

  ```
  MLOpsContext initialized from execution context
  Non-retryable exception in 'read_dataframe': .../runs/index.parquet not found
  Ended MLOps run f3419051-… with status COMPLETED
  ```

  Detection is now wired into the execution path and scoped to *this pipeline's*
  nodes (it was being handed every node in the project, so one ML node anywhere
  turned tracking on for every batch pipeline sharing the config). It also
  honours the flat `mlops_enabled` that `GlobalConfigSchema` documents, not
  just the nested `mlops.enabled`. The dead property and its helpers are gone.

  `mlops_enabled` is now `Optional[bool]` defaulting to `None`. It was `True`,
  and — the same seam as `min_pass_rate` — a default reaches the engine
  indistinguishable from a value the user typed, so auto-detection could never
  run. Unset now means "decide per pipeline"; the resolved master switch in
  `CoreSettings` is unchanged.

- **A declared `sanity_gate` was never consulted.**
  The sanity phase defaults to `fail_fast: true`, and that raise happens inside
  the per-check loop — before the gate is evaluated. So
  `sanity_gate: {behavior: warn_only}`, which says "log this and carry on",
  hard-failed the node, and `skip_downstream` surfaced as a *failed* node rather
  than a blocked one, meaning the run came back FAILED instead of GATE_BLOCKED
  and no descendant-skip cascade ran. When a gate is declared it now decides,
  matching the `data_quality` phase. With no gate declared, fail-fast is
  untouched: that is this phase's documented behaviour.

- **A blocked quality gate was rendered as `❌ Unknown Error`.**
  `classify_error` matched regexes against the message and never looked at the
  exception object it had always accepted, so an outcome the engine deliberately
  produces — with the rules it tripped on attached — was reported as an unknown
  failure. It now reports `⚠️ Quality Gate Blocked` with the triggered rules as
  the suggested next step.

- **`file_size_bytes` in the run certificate was the size of a directory entry.**
  Every Spark-written dataset is a directory of `part-` files, and
  `_capture_file_stat` called `os.stat` on it — 192 bytes, the same figure
  whether the dataset held five rows or five million. In a document whose purpose
  is to describe what a run produced, that is a field that looks like evidence
  and carries none. It now sums the files, recursing into partition directories.
  Measured on `medallion_basic`: 249 bytes for the 5-row gold output, 5,820 for
  the 488-row silver one.

### Removed

- **The specialized context hierarchy.** `ContextFactory`, `MLContext`,
  `StreamingContext`, `HybridContext` and `BaseSpecializedContext` (~250 lines)
  were exported from `ducta.setting` and constructed by nothing: both the CLI and
  the API build a plain `Context` through `ContextLoader`. Every validation they
  carried therefore never ran.

  Two of those validators could not simply be moved, because they encode a
  configuration model the engine abandoned: `MLValidator` requires a `model`
  block on every ML node, but the engine decides a node is ML from `ml_stage` /
  `pipeline.type == ml` / `split` and never reads `model`; `HybridValidator`
  requires a hybrid pipeline to contain streaming *and ML* nodes, while
  `HybridExecutor` classifies into batch and streaming. Enabling either would
  have rejected configurations that run correctly today, so both are removed
  along with `setting.validators.StreamingValidator` (distinct from the live
  `stream.validators.StreamingValidator`).

  What was worth keeping is now in preflight, where it runs: streaming output
  formats are validated against the format policy (previously only their
  *presence* was checked), and `spark.streaming.*` keys are reported as a
  warning — they belong to the legacy DStream API and are inert under Structured
  Streaming, so the tuning a user believes they applied silently does not happen.

  Removing public API is only appropriate before the schema is declared stable;
  that is the gate to leaving alpha and this is on the near side of it.

### Added

- **A `streaming_basic` project template.** `ducta template --template
  streaming_basic` scaffolds a working Structured Streaming project: a
  `file_stream` source (so it runs with nothing installed but Spark), a
  registered transform, per-node checkpoints, and seed events of which two are
  dropped downstream so bronze and silver visibly differ — verified end to end at
  5 rows and 3.

  Streaming was the pipeline type with the least guessable configuration and the
  only scaffold missing. Three shapes in particular fail late and unhelpfully,
  and each was found by building this against the running engine rather than
  from the docs: the trigger is `{type, interval}` rather than Spark's
  `{processingTime: ...}`; a transform is referenced by `function.key`, not
  `function.name`; and `file_stream` takes `file_format` and a top-level
  `schema`, with the path under `options` — a schema nested in `options` reaches
  Spark, is ignored, and surfaces as "Schema must be specified when creating a
  streaming source DataFrame".

  `TemplateFactory` now derives both its registry and `--list-templates` from one
  table, so a new template cannot leave the listing behind, and the project
  scaffolding common to every template moved to a `BaseTemplate`.

- **`ducta config validate` gave false all-clears on configs that were plainly
  wrong.** `QualityCheckEntrySchema` and `NodeSchema` are `extra="allow"` on
  purpose — plugin checks registered through `register_check` define their own
  parameters, and streaming nodes carry inline connector configs no fixed schema
  can enumerate — so anything misspelled inside those blocks validated clean and
  then changed behaviour in silence. Measured on the `medallion_basic` scaffold:

  - `row_cont:` instead of `row_count:` reported *"✓ etl: OK"*, and the run then
    failed as **"Quality gate blocked: 1 ERROR failure"** — a config typo
    presented as a verdict about the data, discovered only after a full run.
  - `row_count: {minimum: 400}` reported *OK*; the key is dropped, so the check
    ran with no minimum and passed on any row count at all.
  - `quality_gate: {behavior: halt_everything}` reported *OK*, then fell back to
    `skip_downstream` at runtime, so the gate did not do what the config said.
  - `dependencie:` instead of `dependencies:` reported *OK* and silently lost
    the ordering it was meant to declare.

  Preflight now validates check names against `QUALITY_CHECKS_REGISTRY`
  (resolving `type:` exactly as the engine does), check parameters, and gate
  behavior — as errors — and reports unknown node keys as a warning, since an
  unrecognised key may be a forward-compatible extension rather than a mistake.
  Shared `quality.profiles` are validated the same way. `extra="allow"` is
  unchanged; the knowledge lives where the registry is.

  The unknown-node-key warning's allow-list was built from `NodeSchema` plus a
  short hand-written set, and missed keys other layers read: `source`,
  `columns`, `where`, `sources` and `options` (ingestion — `source` is
  *required* by preflight's own `_check_ingestion_node`), `depends_on`
  (streaming wave ordering), `execution_mode` and `execution_mode_max_rows`
  (vectorized execution), `metrics`, `model_artifacts`, `mlops_enabled` and
  `ml`. So the warning fired on every ingestion node, every vectorized node,
  every ML node and every streaming node, telling users their working
  configuration was being dropped. Each entry now names the module that reads
  it, because a warning nobody can trust is worse than no warning: it trains
  people to ignore the one that is real.

  For the parameter check, every built-in check now declares a `CONFIG_PARAMS`
  class attribute. A check that declares none — any third-party check — has its
  *name* validated and its parameters left alone, so no plugin is second-guessed.

- **A one-character config typo cost a JVM startup.** `run_pipeline` read the
  pipeline config through `self.batch_executor`, and that property builds
  `BatchExecutor` → `DataOutputManager` → `UnityCatalogManager`, whose
  constructor asked the session whether Unity Catalog was enabled. So preflight
  rejected the config *after* a Spark session had been created and its banner
  printed — about 10s, on projects that never touch Unity Catalog, and contrary
  to the documented promise that "the session is created lazily on first genuine
  access". `UnityCatalogManager` now resolves that answer lazily on first
  `is_enabled()`, and preflight runs before anything constructs an executor. The
  same typo now fails in **0.97s with no Spark output at all**.


- **A certificate's signature could be removed without `verify` noticing.**
  `signature` and `key_id` cannot live inside the hash they sign, so
  `verify_certificate` excluded them from the content it recomputed. Deleting
  both fields and recomputing `certificate_hash` therefore produced a forged
  certificate that verified as *"hash matches — untampered"*, `ok=True`, exit
  0 — **even when handed the correct signing key**. The README's claim that
  "forging it requires the key" was defeated by removing two JSON fields.
  Certificates are now schema `1.3` and carry `signed` *inside* the hashed
  content, so signing changes the hash and a stripped signature no longer adds
  up: `verify` rejects it with or without a key. A pre-1.3 certificate carries
  no such marker — given a key, `verify` now reports it *unverifiable* rather
  than passing it, because "never signed" and "signature removed" are
  genuinely indistinguishable there.

- **A node that produced zero rows was recorded as a success that wrote
  data it never wrote.** `DataOutputManager.save_output` skipped the write
  outright for an empty DataFrame, and the Spark writer rejected empty frames
  besides. Zero rows is a legitimate result — a day with no orders, a filter
  that matched nothing — so with `write_mode: overwrite` the target kept the
  *previous* run's rows while the node was recorded `success`, the certificate
  listed the dataset under that node's `outputs`, and `evidence_complete` said
  `true`; only the missing entry in the certificate's `outputs` fingerprint map
  contradicted it, and nothing checked that. Reproduced end to end on the
  `medallion_basic` scaffold: exit 0, `status: success`, and gold on disk from
  an earlier run. An empty result with `write_mode: overwrite` now truncates
  the target, which is the period's actual answer; any other write mode is
  still a genuine no-op but is recorded as an evidence gap, so the certificate
  reports `evidence_complete: false` instead of looking complete.

- **`gate_blocked` and `skipped` were lost on exactly the runs that needed
  them.** `NodeExecutor.execute_nodes_parallel` assigned both after its
  `try/finally`, and `coordinate()`/`cleanup()` raise on any node failure — so
  a run where one branch was gate-blocked or skipped for missing inputs and
  another failed reported a bare failure naming neither. Both are now assigned
  inside the `finally`.

- **A node still running when the run ended left no trace in the
  certificate.** A started future cannot be cancelled and a thread cannot be
  killed, so after a fail-fast abort those nodes keep writing datasets and
  fingerprints past the point the certificate is sealed. The grace period is
  unchanged, but a node that outlives it is now recorded as an evidence gap
  rather than silently omitted from a certificate that claims to be complete.

- **`ledger_for` built a fresh ledger on every call for dict-shaped
  contexts.** `getattr`/`setattr` do not reach into a dict and the `setattr`
  failure was swallowed, so no caller shared a ledger — and because
  `_record_failures` lives per instance, `evidence_complete` was permanently
  `true` and every gap was discarded. That is the one failure `RunLedger`
  exists to prevent, on the one context shape where it silently did not apply.

- **Malformed `input`/`output` declarations erased dependency edges in
  silence.** `_normalize_dataset_keys` returned `[]` with no output for a dict
  whose values are not dataset keys, while `gate.input._get_input_keys` raises
  `ConfigurationError` on the same value — so the DAG scheduled the node with
  no predecessors, ran it concurrently with the node that feeds it, and only
  then failed, after wasting the producer's work. Inference still cannot raise
  (it runs in read-only paths), but it now warns and names the node; an inline
  connector config (`{format: ..., path: ...}`) is recognised as such instead
  of having its values read as dataset names.

- **`fingerprint_mode: sample` was not reproducible on Spark.** It hashed
  `df.limit(n)`, and `limit` has no defined order on a distributed DataFrame,
  so two runs over byte-identical data could hash different rows — and
  `certify verify --reproduce` would report a divergence that had not happened.
  The sample is now the N rows with the lowest row-hash, chosen by content, so
  it is the same sample every time (`spark-minhash/v3`).

- **`_code_fingerprint` compared mtimes, not code.** An mtime is a property of
  the filesystem: it does not survive a clone or a container rebuild, and
  anything that restores timestamps (`rsync -t`, `tar -p`, a restored backup)
  can put *different* code on disk under a timestamp the chain-state marker
  still recognises — reusing outputs the code on disk would not produce. It now
  hashes module source content. Markers from the old scheme stop matching, so
  the first run after upgrading recomputes once and re-records.

- **The `${VAR}` credential guard missed obvious names.** Matching only whole
  separator-delimited components let `${DB_PASS}` and `${APIKEY}` through.
  Names are now split on camelCase boundaries too, and a short list of
  unmistakable words is matched as a trailing word — so `${myApiKey}` and
  `${dbpassword}` are refused while `${MONKEY_DIR}`, `${TOKENIZER_PATH}` and
  `${PASSWORDLESS_MODE}` still interpolate.

### Added

- **`fingerprint_mode: exact_crypto`.** The default `exact` aggregates
  `xxhash64` row hashes with count+sum+xor — an excellent detector of
  *accidental* change, but xxhash64 is not a cryptographic hash, so someone who
  can write the dataset could construct rows that land on the same digest with
  different content. That is the same adversary the HMAC signature exists for.
  `exact_crypto` hashes each row with SHA-256 and combines them with an
  additive multiset digest: order-independent like `exact`, aggregated inside
  Spark (no collecting row hashes to the driver, so memory is constant in the
  row count), and duplicate-sensitive because addition — unlike XOR — does not
  cancel. Opt-in; `exact` remains the default.

- **`on_missing_input: skip | fail` on a node.** A missing input raises
  `MissingDependencyError`, which the coordinator treats as a skip ("never a
  failure") — so `fail_fast: true` was, confusingly, the setting that made a
  node *not* fail. `fail_fast` still decides whether to pre-check;
  `on_missing_input` now names what the result means, and defaults to `skip`,
  the existing behaviour.

### Changed

- **`certify show`/`certify verify` used to hide the one thing that most
  affects how much a certificate can be trusted.** A dataset fingerprinted in
  `sample` or `schema` mode looked identical, in the default pretty view, to
  one fingerprinted `exact` — the difference only appeared under `--json`.
  Concretely: a project running `fingerprint_mode: "fast"` (which maps to
  `sample`, a 100-row head hash) produced certificates whose CLI-rendered
  summary was indistinguishable from a full-table guarantee, unless someone
  went and read the raw JSON. `certify show` now prints a `Fingerprint`
  column on every dataset (`exact`, or `sample (100 rows)`/`schema-only` in
  yellow), and `certify verify` — the command run specifically to decide
  whether to trust a certificate — now warns by name when any input or
  output was measured in a non-`exact` mode. The summary panel also surfaces
  `evidence_complete: false` (with its `evidence_gaps`) as a visible warning
  row instead of only in `--json`, and an unsigned certificate now reads *"no
  — hash only, not tamper-evident"* rather than a bare *"no"* that reads as
  neutral when it is not.

- **The `medallion_basic` scaffold now demonstrates the product instead of
  describing it.** `extract`, `transform` and `load` were all pass-throughs
  (`return source_data` / `return raw_data` / `return clean_data`), so a
  "medallion" template produced three byte-identical layers — verified: bronze,
  silver and gold came out with the same fingerprint. The five-row sample was
  spotless and the checks were `row_count: {min: 1}` and a null_rate against
  data with no nulls, so nothing could ever be caught, and **`quality_gate`
  appeared nowhere in the 1,763-line generator** — the headline feature was not
  demonstrated by any template.

  The sample data is now deliberately dirty (500 orders, 12 with a missing
  `amount`, 8 verbatim duplicates) and each layer does real work, so a first run
  reads: 508 rows in bronze, 488 in silver after deduplication and dropping
  incomplete rows, 5 in gold after aggregation — all three visible as separate
  row counts and fingerprints in the certificate. Silver's `null_rate` and
  `duplicates` checks pass *because* `transform` cleaned the data, backed by
  `quality_gate: {max_errors: 0}`; the generated README shows how to break the
  transform and watch the gate block the run with gold never written.

### Fixed

- **Quality checks decided correctly and then misreported the decision.** Three
  separate defects, none of them in the check logic, all of them in the only
  part a reader of a persisted report ever sees:

  `min: 0` printed as `-∞`. The bounds were formatted with `min_val or '-∞'`,
  and `0` is falsy, so a range check pinned at zero advertised a bound it was
  not enforcing. `row_count` additionally used `'∞'` for *both* ends, so a
  `max: 0` fell the same way and the lower bound read as positive infinity.
  Both now go through `_format_bounds`, which only substitutes an infinity for
  a genuinely absent (`None`) bound.

  `DuplicateCheck` said "No duplicate rows found" on every pass — including a
  pass *within tolerance* — and discarded the count and rate it had just
  computed, so `details` carried nothing to trend against. The official demo hit
  this on real data: **15 duplicates in 907 rows, reported as none**, and had to
  carry a nine-line comment in its node config warning readers not to believe
  the line. The pass branch now reports the measured count and rate against the
  threshold, with the same four `details` fields the failure branch already
  emitted.

  `severity: "warning"` on a node's check was accepted by the config object and
  read by nothing: `_create_result` resolves `severity or self.severity`, the
  check's *class* default. The check stayed an ERROR and still counted against
  `quality_gate.max_errors` — the opposite of what the key asks for. It is now
  applied, before `fail_fast` is consulted, so a downgraded check no longer
  aborts the run. An invalid value (`severity: "wrning"`) raises
  `QualityConfigError` rather than silently meaning ERROR, and is resolved
  before the check runs so it is reported as the config error it is instead of
  surfacing as "check execution failed".

  **Compatibility:** the severity fix can change gate outcomes. A config that
  already carries `severity: "warning"` was being counted as an error and is now
  counted as a warning, so gates that blocked on it will start passing. Nothing
  that previously passed can begin to fail.

- Renaming a named check instance for the report reset its `executed_at` to the
  rename time, so every aliased check reported when it was relabelled rather
  than when it ran.
- **The example custom check in every scaffold called a method that does not
  exist.** `adapter.count_where(...)` is not part of `DFAdapter` (the method is
  `filter_where`), and the resulting `AttributeError` was caught by the check's
  own `except` and returned as a *failed* `CheckResult` — so anyone activating
  the documented extension point would have concluded their data was bad.
- Scaffolded `custom_checks.py` documented activation in TOML while the
  generator defaults to YAML.
- The generated project README described a directory layout the pipeline never
  creates (`data/raw/`, `data/processed/`), never mentioned run certificates or
  quality gates at all, called an alpha scaffold "production-ready", and wrote
  `Ducta --help` for an executable named `ducta`.
- Generated `requirements.txt` asked for `Ducta>=0.1.0` plus a loose `pyspark`
  pin; it now asks for `ducta[spark]>=0.1.1`, the combination the project
  actually declares.
- The `ml_ready` template reuses medallion's `extract`/`transform` nodes on its
  own numeric feature table, so it now retunes the inherited schema and quality
  checks to its own columns rather than inheriting assertions about
  `order_id`/`amount`.
- README: the flagship node example used `null_rate: {column, max}`; the check
  reads `columns` (a list) and `threshold`, so the written example silently
  checked every column at the default 5% threshold instead of what it said.

### Security

- **Run certificates measured far less than they claimed on Spark.** The
  fingerprint module was written for pandas (`df.shape[0]`, `len(df)`,
  `df.iloc[...]`, `df.to_json()`), none of which exists in Spark — the only
  engine that executes a pipeline. Verified against Spark 3.5.9 on 5,000 rows:
  `row_count` was always `null`; `fast` (the default) silently degraded from
  head+middle+tail sampling to `head(100)`, so a corrupted *last* row produced
  an identical fingerprint; and `full` hashed `str(df)` — the schema repr —
  making any two datasets sharing a schema indistinguishable, i.e. `full` was
  strictly weaker than `fast` while the docs presented it as the deeper option.
  `--reproduce` and `certify diff` were therefore comparing
  `(schema, null, first 100 rows)`.

  Fingerprinting is now engine-native. Spark uses an order-independent multiset
  digest — `xxhash64` per row, aggregated by `count`/`sum`/`bit_xor` — which
  detects a changed cell anywhere, a duplicated row, or a deleted row, and is
  correctly insensitive to physical row order and partitioning. (`bit_xor` alone
  would be wrong: identical rows XOR to zero, so an even number of a duplicate
  would cancel out.) `row_count` is real. Modes are now `exact` (default),
  `sample` and `schema`; `fast`/`full` still parse, mapping to `sample`/`exact`.

  **Every fingerprint value changes.** Each one now records the `engine` and
  `algorithm` that produced it, and comparisons across algorithms return *not
  comparable* instead of reporting a data change that never happened — so the
  first run after upgrading does not trip `fingerprint_policy` or fail
  `--reproduce`. Certificate `schema_version` is now 1.2.

  Root cause: both fingerprint test modules had zero Spark coverage, and one
  test asserted the tail-corruption guarantee *on pandas* and passed. The suite
  validated an engine that pipelines never run on. Guarantees are now written
  once and parametrized over engines
  (`tests/integration/test_fingerprint_engines.py`).
- **A failed fingerprint is no longer silent.** `_record_fingerprint` swallowed
  every failure at debug level, so a certificate whose fingerprints never
  computed still verified and still looked complete while attesting to nothing.
  Failures (and silent degradations to a weaker mode) now go through the run
  ledger, which raises them to WARNING and marks the certificate
  `evidence_complete: false` with the reason in `evidence_gaps`.

### Performance

- **Node outputs are cached before the quality phase.** Every structural check
  ran its own `count()` with no memoization, and nothing was cached between the
  checks and the write, so the README's own three-check example recomputed the
  node's whole lineage about four times. The output is now materialized once and
  shared by the checks, the fingerprint and the write, reusing the existing
  `resource_context` lifecycle for the `unpersist`.

- **`python-jose` replaced with `PyJWT`.** python-jose pulls in `ecdsa`, whose
  Minerva timing vulnerability (CVE-2024-23342) is unfixable in pure Python and
  has no planned patch, so it would have shown up as an unresolvable *high* in
  every dependency scan of a Ducta install. Ducta only ever signs with HS256,
  so the ECDSA code was dead weight; PyJWT delegates to `cryptography`. Token
  encode/decode, expiry and revocation behaviour are unchanged.
- **UI dependencies with known advisories upgraded.** `react-router-dom` (open
  redirect, XSS via `RSCErrorHandler`, CSRF on document requests, DoS via route
  matching) and `axios` (SSRF via `NO_PROXY` bypass, several prototype-pollution
  gadgets). `dompurify` is pinned through an override because it reaches us via
  `monaco-editor`, which still allows a vulnerable range. Shipped UI
  dependencies now audit clean.
- **The web terminal signalled only the shell on disconnect.** `os.kill(pid, 9)`
  left everything the shell had started — a build, a `tail -f`, any background
  job — orphaned and running on the host after the browser tab closed, because
  `pty.fork()` makes the shell a session leader and its children live in its
  process group. Now signals the group.
- Added `SECURITY.md`: private reporting, supported versions, an explicit threat
  model (what the CLI's config-is-code model puts out of scope), and the
  production checklist that `api/main.py` and `docs/server_api.rst` had been
  pointing at for some time without it existing.

### Fixed

- **CI was red in three jobs, and had been silently.**
  - `install-matrix` smoke-tested `from ducta.core.executor import
    PipelineExecutor`; that module became the `ducta.core.executors` package in
    an earlier refactor, so the job that exists to prove the published artifact
    is importable had been failing on its own import.
  - `ruff check` is a blocking gate and had four outstanding errors.
  - `tests/integration/test_pipeline_e2e.py` still assumed the flat
    `.ducta/runs/<run_id>/` certificate layout after it became
    `.ducta/runs/<env>/<run_id>/`, so it picked the `dev` directory and failed
    on a missing file. It now discovers runs via `iter_certificate_dirs`, so it
    no longer encodes a layout it should not know about.
- **A released wheel could ship without the web app.** `pyproject.toml` bundles
  `src/ducta/ui/dist`, which is gitignored — it exists only after the UI is
  built. `poetry build` on a clean checkout therefore produced a wheel with no
  UI and no error, and `ducta server start` would 404 on `/`. CI now builds the
  UI before packaging and asserts the wheel contains it, and a new `release.yml`
  makes that sequence the only path to publishing.
- **Fire-and-forget database writes could be garbage-collected mid-flight.**
  `_spawn_db_task` kept no strong reference to the task it created, and the
  event loop holds only a weak one. What those tasks persist is the execution
  record itself, so a collected task meant a run silently missing from the
  database with nothing logged.

### Added

- **A declared public API.** The top-level `ducta` package now re-exports the
  27 names that are supported — executor, context, certificates, the quality
  and I/O extension points, and every error type — resolved lazily so
  `import ducta` still costs nothing on a bare install with no Spark. Anything
  reached through a deeper path is internal. This is the prerequisite for
  "declare the configuration schema and the public Python API stable", which is
  the gate to leaving alpha: without a façade, declaring stability would have
  meant freezing every internal module path anyone happened to import from.
- **Run certificates report their own completeness** (`schema_version` 1.1).
  `RunLedger` swallows recording failures on purpose — bookkeeping must never
  be the reason a pipeline fails — but it swallowed them at DEBUG, so a
  certificate assembled from a ledger that had dropped a node outcome was
  sealed looking exactly like a complete one, which is the failure the ledger
  exists to prevent. Failures now log at WARNING and surface as
  `evidence_complete: false` plus an `evidence_gaps` list, both covered by the
  certificate hash. Older certificates verify unchanged.
- Dependency audit job in CI: `npm audit --omit=dev` is blocking for the
  packages that ship in the browser; `pip-audit` and the build toolchain are
  advisory with the specific backlog named in the workflow.
- `scripts/dump_openapi.py`, which `npm run spec:generate` had always invoked
  but which was never committed.
- A dedicated Run Certificates tutorial (`docs/tutorials/certificates.rst`):
  certificate anatomy, the three levels of proof (hash, signature,
  `--reproduce`), fingerprint modes and their trade-offs, and the full
  `ducta certify` CLI walkthrough. Certificates previously had no doc of
  their own — everything about them lived in the top-level README and the
  source.

### Changed

- `ducta.api.repository` (adapters for hosted git forges) renamed to
  `ducta.api.vcs`. It sat one plural away from `ducta.api.repositories` (the
  data-access layer over configs, nodes, pipelines and projects) while meaning
  something entirely unrelated — a typo that imports cleanly and fails
  elsewhere. Internal module; no public API change.
- `ruff format` is now a blocking CI gate (the backlog reached zero).
- Roughly 170 fewer mypy errors, and `union-attr` down from 230 to 59. Three
  hotspots accounted for most of them, all the same shape: an attribute typed
  `Optional` but guaranteed non-None past an initialisation or availability
  check, so ~100 accesses read as "might be None" and the one place it genuinely
  might got no more attention than the ninety-nine where it could not. Each is
  now a property that states the invariant and raises a named error.

## [0.1.1] - 2026-08-29

Ships every security fix below to users of `0.1.0`, which is why it went out as
a patch rather than waiting for `0.2.0`. **It is not a pure patch release:** it
also carries behavioural changes (the per-environment certificate layout, the
CORS default) and new features. Ducta is alpha and the API is explicitly not
declared stable yet — read *Changed* before upgrading.

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
- **Ingestion nodes built SQL by string concatenation, unsanitized.**
  `type: ingestion` composed `SELECT {columns} FROM {table} WHERE {where}` from
  three config fields and handed it to the JDBC driver. `columns` was checked to
  be a list of strings but not that each was an identifier, and `table` and
  `where` were not checked at all; a declared `query` went straight through. The
  project already ships `SQLSanitizer` for exactly this, and `sqlglot` is a core
  dependency because of it — the ingestion node was simply the one SQL path that
  never called it. Identifiers are now matched against an identifier pattern and
  both the composed statement and any declared `query` go through the sanitizer.
- **`UnityCatalogDDL.vacuum()` interpolated its retention unchecked.** Every
  other method in that class escapes its arguments; this one formatted `hours`
  straight into `RETAIN {hours} HOURS`. Now coerced to `int`, raising
  `ConfigurationError` otherwise.
- **A web page could open the embedded terminal.** `CORSMiddleware` only sees
  the ASGI `http` scope, and the same-origin policy does not apply to WebSockets
  at all — a browser will open one cross-origin and no CORS header stops it. So
  neither `/api/ws/terminal` nor `/api/ws/logs/{id}` checked `Origin`. With
  `TERMINAL_ENABLED=true` and auth disabled (the default), the terminal's
  remaining defence was a loopback check on the TCP peer — and a tab in the
  user's own browser *is* a loopback peer, so any site they visited could
  `new WebSocket(...)` its way to a shell. This is the same reasoning already
  recorded above for CORS ("binding to loopback is no defence here: the browser
  is on the loopback host"); it had not been carried across to this channel.
  Both handshakes now validate `Origin` before `accept()`, accepting the CORS
  allow-list, the app's own origin (the packaged UI is same-origin and
  deliberately absent from `CORS_ORIGINS`), and requests with no `Origin` at all
  (non-browser clients, which are not the threat).
- **An empty `GIT_CLONE_ALLOWED_HOSTS` meant "clone from anywhere".** The clone
  target comes from a caller-supplied `?source=`, so a networked deployment
  would fetch whatever internal URL it was pointed at, with the server's own
  network position (SSRF). The field's own description warned about this while
  shipping the permissive value. Left unset, it now defaults to the public
  forges (`github.com`, `gitlab.com`, `dev.azure.com`, `bitbucket.org`) outside
  development; development keeps the open behaviour, where cloning from a LAN
  mirror or a local bare repo is normal and the API binds to loopback.

### Changed

- **The three table screens share one implementation.** Execution history,
  experiments and the model registry each had a hand-rolled `<table>` with its
  own inline styles: they disagreed on header weight, on padding, and on whether
  the header even had a rule beneath it, and none could sort, keep the header in
  view while scrolling, or show a loading state inside the table. A new
  `DataTable` takes declared columns and owns sorting, selection, the scroll
  container and the empty/loading/error states — so every column is now sortable
  and the header stays put, which is new behaviour on all three.
- **Destructive actions ask in the app's own dialog.** `window.confirm()`
  prefixes the host ("127.0.0.1:8000 says…"), cannot be styled, gives a delete
  and a rename the same weight, and after a few uses the browser offers to
  suppress it — at which point the destructive action runs unconfirmed. The new
  `ConfirmDialog` builds on the existing `Modal` (focus trap, Escape, focus
  restore) and adds a danger tone plus typed confirmation, now required to
  delete a model version that is serving production. The unsaved-changes guards
  in the code editor moved across too.
- **Loading shows the shape of what is coming.** The execution history replaced
  a centred "Loading…" that swapped the whole view with skeleton rows inside the
  table, so the filter bar stays put and nothing jumps when data lands.
- **Execution priority now decides execution order.** `ExecutionPriority`
  ranked the queue's heap, but `_run_execution` awaited `dequeue()` and threw
  the result away, then ran its own execution — so the id that entered the
  "active" set was whichever the heap surfaced, not the one that was running.
  The concurrency cap held by coincidence; the ordering did not exist, and
  `GET /executions/queue` reported active ids that were not the running ones.
  `dequeue()` is replaced by `acquire_slot(execution_id)`, which returns only
  once *that* execution owns a slot. A `prod` run now genuinely preempts a
  queued `dev` one, and the active set is exactly what is running.
- **The UI no longer keeps the access token in `localStorage`.** The backend
  issues it as an `httpOnly` cookie precisely so page scripts cannot read it,
  and the UI persisted a second copy that any script could. The token now lives
  in memory for the tab's lifetime; after a reload `ProtectedRoute` exchanges
  the cookie for a fresh one via `/auth/refresh` before deciding whether to
  redirect. The persisted `user` is unchanged, so nothing flashes. There is no
  known XSS vector in the UI today — this removes the value that one would
  otherwise be worth.
- **The CLI now exits with a meaningful status code.** Previously every
  invocation exited 0 (see *Fixed*), so this is a new observable contract rather
  than an adjustment to an old one. Scripts that only checked for a non-zero
  exit will start seeing failures they previously missed:

  | Code | Meaning | Example |
  |---|---|---|
  | 0 | success | a run that completed all of its work |
  | 1 | unexpected error, interrupted | an internal bug, `Ctrl-C` |
  | 2 | the configuration could not be loaded or is invalid | unknown `--env`, failed preflight |
  | 3 | the request itself was invalid | unknown `--pipeline`, a missing or malformed argument |
  | 4 | the run did not complete its work | a node failed or timed out, a quality gate blocked |

- **A blocked quality gate no longer reports success.** `skip_downstream` — the
  default gate behaviour — deliberately lets a run finish without raising, and
  four of the five places that start a pipeline discarded the result entirely,
  so a run that rejected its data was indistinguishable from a clean one. The
  CLI (including the layered path and `--sweep`), `ducta certify --reproduce`
  and the API now all read the outcome. `ExecutionStatus` gains
  **`gate_blocked`**, distinct from `skipped` (data absent) and `failed`
  (something broke) — a new value in API responses.
- **A blocking quality gate means the same thing in hybrid pipelines as in
  batch.** Hybrid counted `gate_blocked` as a batch-phase failure, so the same
  gate aborted a hybrid run with an exception — taking the rest of the pipeline
  chain with it — while a batch run finished as `GATE_BLOCKED`. Hybrid now halts
  before the streaming phase (which would consume data that was never produced)
  without reporting a failure.
- **Quality gates are less strict by default.** `min_pass_rate` now defaults to
  `0.0` (off) instead of `1.0`. The old default contradicted `max_warnings: -1`
  sitting beside it: the pass rate counts every failed check regardless of
  severity, so a gate configured with nothing but `enabled: true` blocked on the
  very warnings the other setting declared tolerable. Out of the box a gate now
  means exactly one thing — any ERROR blocks. Set `min_pass_rate: 1.0`
  explicitly to restore the previous behaviour.
- **`ducta.console.core.DuctaError` now derives from
  `ducta.core.errors.DuctaError`,** and its `exit_code` is a plain `int` rather
  than an `ExitCode` enum member. The two hierarchies were unrelated classes
  that merely shared a name. `console.core.ExecutionError` is now an alias of
  the engine's — it never had a `raise` site of its own.
- **`SQLSanitizer` accepts set operations.** `SELECT … UNION SELECT …` parses
  with a `Union` at the AST root, which was not in the allow-list, so an
  ordinary read-only analytics query was refused. `Union`, `Intersect`, `Except`
  and `Subquery` are now allowed; the lexical and keyword layers still see the
  whole statement, and the dangerous-operation scan already walked every
  `Select` in the tree.
- **`LayerContextBuilder.build_context_args()` returns the environment** in its
  result dict. It used to accept an `env` argument and ignore it, which is how a
  caller came to drop it (see *Fixed*). `LayerConfig.environments_path` is
  removed — it was assigned and never read.
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

- **`DataTable`, `ConfirmDialog` and `Skeleton`** in `components/ui/`, with
  Storybook stories and 31 tests. They are the first components written entirely
  against the spacing and type scales in `theme/tokens.css` rather than ad-hoc
  pixels — the scales existed but the screens used 271 raw px values against 115
  token references, which is why no two tables matched.
- **Real tests for the API client, the execution queue, and the WebSocket
  handshakes** — three areas with no working coverage. `client.test.ts` had 20
  tests and exercised `client.ts` in one of them; the other 19 built a literal
  or reimplemented the interceptor inline and asserted on their own
  reimplementation (one carried the comment *"The actual implementation is in
  client.ts lines 31-47"*). They are replaced by ten that drive the real axios
  instance through a swapped adapter, so the suite is seven tests smaller and
  covers considerably more. `ExecutionQueue` had no tests at all, which is how
  its priority ordering came to do nothing.
- **Tests for five paths that had none**, each of which was hiding one of the
  defects above: `UnifiedCLI.run`'s exit codes, `PipelineExecutor.run_pipeline`
  driven end to end for a batch pipeline, `_execute_unified_hybrid_pipeline`,
  `_fail_timed_out_nodes`, and streaming resource-conflict detection. The
  run-status bug is the clearest case for why they were needed: ten unit tests
  covered `resolve_status` and `absorb_trace` as pure functions and all of them
  passed while the facade called the two in the wrong order.
- **Spark integration tests** (`tests/integration/`, marked `@pytest.mark.spark`).
  The suite had 1259 tests running in 3 seconds against a mocked Spark and *zero*
  tests behind the `spark` marker, so CI installed a JDK and pyspark for nothing
  and the primary execution engine was never exercised. These cover the gate
  against real DataFrames and run the README walkthrough end to end through the
  console entry point (template → list-pipelines → start → certificate verify).
  The first run of them found the `pyspark.sql.pandas` / `distutils` gap below.

### Fixed

- **The UI never actually loaded the typeface it was designed in.** Inter and
  JetBrains Mono came from the Google Fonts CDN via a `<link>` in `index.html`,
  and the production CSP is `default-src 'self'; style-src 'self'` with no
  `font-src` — so the stylesheet was blocked, the font files would have been
  too, and every real user saw the system stack. Development runs a wide-open
  CSP, so it looked right exactly where it did not matter. Both faces are now
  served from `/fonts`, which also removes a hard dependency on an external CDN
  (Ducta is deployed on-prem, often on networks that cannot reach it) and the
  transfer of client IPs to Google. They are variable fonts, so this is 80 kB
  for the whole weight range: the vendored set shipped seven files whose
  contents were byte-identical per family, declared at fixed weights, which
  would have rendered 600 and 700 identically.
- **Two stylesheets were never imported, so their rules had simply never
  applied.** The pipeline error page rendered unstyled and the pipeline view had
  no responsive behaviour at all, despite both files existing with the right
  rules in them. The MLOps tabs' shared stylesheet was in the same state. Two
  further theme files contained only orphaned section comments and were removed.
- **A 401 whose refresh produced no usable token resolved with `undefined`.**
  `getToken()` discards a token within 30s of expiry, so `/auth/refresh` could
  succeed and still leave nothing to retry with — and the axios interceptor then
  fell off the end of its 401 handler and *resolved* rather than rejecting. The
  caller's `response.data` threw a `TypeError` somewhere unrelated to the actual
  cause. Because that path always returned, the interceptor's own "401 with no
  valid refresh → logout" branch below it was unreachable except for requests
  already marked `skipRetry`. The handler now always returns a response or
  throws, and the logout/redirect it shares with the terminal case runs.
- **`npm run dev` did not proxy `/api`.** The README has documented "Dev server
  (proxies /api to the backend)" all along, but `vite.config.ts` had no `server`
  block, so requests went to Vite itself unless a developer set an absolute
  `VITE_API_URL` — which then made dev cross-origin. Added, with `ws: true` so
  the log-stream and terminal WebSockets reach the backend too. Dev is now
  same-origin, like the packaged UI the API serves from `ui/dist`.
- **Every `ducta` command exited 0, including failures.** The console script is
  declared as `ducta.console.wrapper:main` and invoked as `sys.exit(main())`,
  but `wrapper.main()` called the CLI and discarded what it returned — so the
  entry point evaluated `sys.exit(None)`. Every exit code the CLI computed, for
  every failure, was thrown away at the process boundary: no script wrapping
  `ducta` could tell a broken run from a clean one, and no CI step could fail on
  one.
- **Errors raised by the engine exited 1 and returned HTTP 500.**
  `ducta.core.errors` declares an `exit_code` and an `http_status` per class of
  failure, and nothing outside `ducta.core` read either. The CLI caught only its
  own unrelated `DuctaError`, so an invalid configuration, a failed preflight and
  a genuine crash were indistinguishable; the API re-wrapped engine errors as a
  bare `RuntimeError` before any handler could see the type. The CLI now maps
  them to the codes in *Changed* above, the API gains an exception handler that
  answers with each error's declared status, and the execution runner no longer
  destroys the exception — so a failed background execution records the engine's
  structured detail instead of a flattened string.
- **A run's status never reflected what its nodes did.** `run_pipeline` called
  `resolve_status()` in an `else` branch and `absorb_trace()` in the `finally`.
  Python runs `else` first, so the status was always decided against an empty
  node list: `resolve_status`'s failed-node branch could never fire, and its
  `not self.nodes` guard was trivially true. The trace now lands first, and the
  run certificate records the resolved status.
- **A node that finished inside its budget could be recorded as a timeout.**
  The completion loop breaks out as soon as new nodes become ready, leaving
  already-finished futures in the running set until the next pass; the timeout
  sweep judged them by elapsed time alone. Because the first failure aborts the
  run, one deferred completion could fail an entire pipeline. Finished futures
  are now skipped and read for their real result.
- **Streaming resource-conflict detection had never reported a conflict.** It
  compared the starting pipeline against the status snapshots returned by
  `list_running_pipelines()`, which carry the pipeline definition under
  `pipeline_config` and have no top-level `nodes` key — so every running
  pipeline contributed an empty resource set and every intersection was empty.
  Shared Kafka topics, file paths and Delta tables are detected again.
- **`ducta config validate --env <env>` ignored the environment on layered
  projects.** It resolved an environment, passed it to `build_context_args`
  (which ignored it) and then built its `Context` without one — validating
  against the base configuration whatever `--env` said, so any error that only
  exists under an `environments:` override went unreported. The streaming CLI's
  fallback `load_context()` dropped `env` the same way.
- **`RunLedger.start()` created a second ledger.** It constructed its own
  instance instead of going through `ledger_for()`, so the executor facade held
  one ledger and every component below it held another — two locks guarding the
  same list, for a class whose stated purpose is to give that bookkeeping one
  thread-safe implementation.
- **`block_threshold: null` raised a bare `TypeError` from inside gate
  evaluation.** Those two thresholds were coerced at the use site, outside the
  `try/except` that turns every other malformed gate key into a
  `QualityConfigError`.
- **`${MONKEY_DIR}` and `${TOKENIZER_PATH}` were refused as credentials.** The
  guard that stops secrets being interpolated into config matched
  `KEY|SECRET|TOKEN|…` as a substring anywhere in the variable name. It now
  matches per `_`/`-`/`.`-separated component; every real credential name is
  still rejected.
- **A query with an escaped quote was rejected as an injection attempt.**
  `SQLSanitizer` did not understand the SQL-standard doubled-quote escape, so in
  `WHERE note = 'it''s a drop-in'` the rest of the literal was read as bare SQL
  and tripped the keyword denylist. It failed closed, so this refused valid
  queries rather than admitting dangerous ones.
- **Layer import paths accumulated across runs.** `inject_sys_path` only ever
  added, and every layer names its package `src`, so running more than one layer
  in a process (`--all-layers`, the API serving two layered projects) left each
  layer stacked on `sys.path` with a stale `sys.modules['src']` — after which
  the second layer silently imported the first layer's node functions. A new
  `layer_sys_path()` context manager restores both on exit.
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

[0.2.0]: https://github.com/faustinolopezramos/ducta/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/faustinolopezramos/ducta/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/faustinolopezramos/ducta/releases/tag/v0.1.0
