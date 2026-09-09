# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/faustinolopezramos/ducta/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/faustinolopezramos/ducta/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/faustinolopezramos/ducta/releases/tag/v0.1.0
