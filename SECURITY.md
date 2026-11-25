# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through
[GitHub Security Advisories](https://github.com/faustinolopezramos/ducta/security/advisories/new),
or by email to <faustinolopezramos@gmail.com> with `SECURITY` in the subject.

Useful things to include, as far as you have them: the affected version, what
is installed (`ducta` alone or with `ducta-server`, extras such as `spark` or
`ai`), whether authentication was enabled, and the smallest reproduction you can
manage. A proof-of-concept helps but is not
required — a clear description of the flaw is enough to start.

**What to expect.** Ducta is maintained by one person, so acknowledgement
within 5 working days and an assessment within 15. If a fix is warranted it
ships in a patch release with the issue described in the
[CHANGELOG](CHANGELOG.md). Reporters are credited by name unless they ask not
to be.

## Supported versions

Ducta is **alpha**. Only the latest release receives security fixes; there are
no backports to earlier versions.

| Version | Supported |
|---|---|
| 0.3.1 and later 0.3.x | ✅ |
| 0.3.0 | ❌ — upgrade to 0.3.1: its API server lets any signed-in account (a `viewer`) run code in the server process through `POST /api/projects/{id}/quality/failing-rows`, and so sign itself an admin token. |
| ≤ 0.2.x | ❌ — upgrade: the same flaw. |

## Threat model

It matters which of these you are running, because they have very different
exposure.

**The CLI and the engine** (`ducta start`, `ducta certify`, the `core`,
`gate`, `check`, `stream`, `mlrun`, `setting` modules) run *your* configuration
and *your* Python on *your* machine. Configuration is code here: a pipeline's
nodes point at Python functions and business rules are evaluated expressions.
Ducta does not sandbox any of that, and is not trying to. **Treat a Ducta project directory with exactly the trust you
would give a repository of Python scripts** — because that is what it is.

**The API server** (the `ducta-server` package: `ducta-server`, `ducta ui`, the web app)
*is* a security boundary, and is the part this policy is really about. It can
read and write files in the workspace, execute pipelines, run git operations
and clone repositories, and — through `ducta ai` and the web app's AI features —
send project context to a model provider.

### In scope

- Authentication or authorization bypass on any API route.
- Path traversal out of the workspace root.
- SSRF via git clone sources, or injection into the JDBC gateway.
- Bypassing the SQL sanitizer (`ducta.gate.sql`) or the business-rule
  expression validator (`ducta.check.checks.business`).
- Running code in the server process through a request. What the server
  evaluates itself from a request (SQL rules on sampled rows,
  `ducta_server.services.sql_rules`) is interpreted against a short list of
  operations, never turned into code.
- A role seeing what its permissions withhold: rows of a protected environment
  without `data.read.protected` (through any route: preview, the file API, git),
  values of `metadata.pii` columns without
  `data.read.pii`, or the content of a secret file (`.env`, private keys,
  keystores, `.pgpass`, `credentials.json` …) through any route, git history
  included.
- A role changing what its permissions withhold: a protected environment's data
  files without `data.write.protected`, the Production model without
  `model.promote.production`, or the protected environments themselves below
  `DUCTA_PROTECTED_ENVIRONMENTS`.
- Cross-origin access to the API from a web page (CORS, WebSocket origin).
- Certificate forgery against a *signed* certificate — see below.
- Credentials leaking into logs, argv, certificates, error responses, or what
  Ducta sends to an AI model (project context and run errors are redacted
  before they leave: `ducta.redaction`).

### Out of scope

- **Arbitrary code execution through project configuration.** A node's
  `run: module:function` and a Python business rule execute by design, in the run's
  own process. This is the documented model, not a vulnerability. Writing that
  configuration takes `pipeline.write` (developer, admin).
- **Forging an unsigned run certificate.** `certificate_hash` is a keyless
  SHA-256: it detects corruption, not a motivated editor, who can recompute it.
  Set `DUCTA_CERTIFICATE_KEY` for tamper-evidence — a forgery against a signed
  certificate *is* in scope.
- Findings that require an attacker to already have local filesystem or
  process access on the host.
- Vulnerabilities in dependencies with no Ducta-specific exploit path. Report
  those upstream; tell us if Ducta's usage makes them exploitable.

## Production checklist

The API is **local-first by default**: it binds to `127.0.0.1` and ships with
authentication off, so that `ducta-server` works on a laptop with no
setup. Every item below is what you must change before it is reachable by
anyone else. `ENVIRONMENT=production` (the first item) enforces the next
four at startup and refuses to boot otherwise. A server bound to an address other
machines can reach with accounts on refuses the default `JWT_SECRET_KEY`, an
unset or `admin` `DUCTA_ADMIN_PASSWORD` and accounts in SQLite even outside
production; `ducta-server` and `ducta ui` also refuse such an address with
authentication off unless you pass `--allow-unauthenticated`.

- [ ] **`ENVIRONMENT=production`.** This is the switch that turns the rest into
      enforced invariants rather than advice.
- [ ] **`AUTH_ENABLED=true`.** Without it every route — including pipeline
      execution — is unauthenticated.
- [ ] **`JWT_SECRET_KEY`** set to a high-entropy random value
      (`python -c 'import secrets; print(secrets.token_urlsafe(64))'`). Never
      the shipped default.
- [ ] **`DUCTA_ADMIN_PASSWORD`** set to a password of your own. It is the
      password of the `admin` account created at startup; unset, it is `admin`.
- [ ] **`DEBUG` unset or false.** Debug mode returns full tracebacks, source
      and local variables on any unhandled exception.
- [ ] **`CORS_ORIGINS`** listing only the origins that must reach the API.
      Never `*`: with credentials allowed, that lets any site a user visits
      read authenticated responses. Loopback is no defence — the browser is on
      the loopback host.
- [ ] **`ALLOWED_HOSTS`** set to the names users type (e.g.
      `ducta.company.com`) when binding `0.0.0.0`. Unset there, the server
      answers to any `Host` name, which lets a web page reach it through a DNS
      name the page controls (DNS rebinding). On loopback only `localhost`,
      `127.0.0.1` and `::1` are answered.
- [ ] **`RUN_ISOLATION=process`** (the default with `AUTH_ENABLED=true`): each
      run in its own process, without the server's secrets in its environment
      and unable to read its memory. With `thread`, code a developer writes and
      runs can read the server's settings — `JWT_SECRET_KEY` included — and sign
      itself any role.
- [ ] **Nothing secret the runs can reach as files.** A run is still the
      server's OS user: pass `JWT_SECRET_KEY` and `DATABASE_URL` as environment
      variables (not a `.env` next to the server), use PostgreSQL rather than
      SQLite, or run the server in its own container. On macOS a run can also
      list the server's environment (`ps eww`); Linux blocks that. A server
      others can reach refuses accounts in SQLite (a run could rewrite the
      `users` table, roles included) unless `ALLOW_SQLITE_WITH_ACCOUNTS=true`.
      With Docker, `docker compose -f docker-compose.yml --profile accounts up`
      adds PostgreSQL (fill in `.env` from `.env.example`).
- [ ] **Credentials per environment, not one `.env` for all.** A developer's
      code runs as the server's user in any environment it may run in, and can
      read the project's `.env`. "Protected environment" is enforced by the API
      (who may start a run, read rows or files), not by the operating system:
      keep production credentials out of the workspace developers write to — in
      the environment of the server that runs prod, or a secret store that only
      prod runs reach.
- [ ] **`DUCTA_PROTECTED_ENVIRONMENTS`** lists every environment that holds
      real data (default `prod,production`). It is the floor: a project's
      `governance.protected_environments` can add to it, never remove from it,
      because developers edit the project's files.
- [ ] **`RATE_LIMIT_ENABLED=true`** (turned on with auth unless you set it to
      `false` explicitly, which logs a warning), and `RATE_LIMIT_REDIS_URL` if you run more than one worker —
      the in-memory limiter is per-process, so the effective limit otherwise
      multiplies by `WORKERS`.
- [ ] **Accounts beyond `admin`.** The server starts with the one administrator
      (`DUCTA_ADMIN_PASSWORD`). Give everyone else the narrowest role with
      `ducta-server user add <name> --role developer|operator|viewer` (a
      developer can edit and run but not run in `prod`; an operator runs in `prod`
      but edits nothing; a viewer only reads), and `ducta-server user disable <name>`
      when they leave. Passwords are asked for or read from `--password-env`,
      never taken as an argument.
- [ ] **`LOGIN_MAX_ATTEMPTS`** (default 5) wrong passwords for one user from one
      address lock that pair out for `LOGIN_LOCKOUT_SECONDS` (default 300) with a
      `429` and a `Retry-After`. The count is per process: with several workers,
      also limit `/api/auth/login` in the reverse proxy.
- [ ] **`GIT_CLONE_ALLOWED_HOSTS`** restricted to the forges you actually clone
      from. Outside development this defaults to the public forges; widen it
      deliberately, never to everything.
- [ ] **`DUCTA_CERTIFICATE_KEY`** set in the server's environment, if run
      certificates are meant to be evidence rather than checksums. With
      `RUN_ISOLATION=process` the key never reaches a run: the run writes its
      certificate unsigned and the server signs it when the run's process ends,
      so a pipeline's code cannot sign a certificate for a run that never
      happened. The keys of Ducta's AI model (`OPENAI_API_KEY`,
      `ANTHROPIC_API_KEY`, `DUCTA_AI_*`) are withheld from runs too. The
      signature is HMAC: whoever holds the key to verify can also sign, so give
      it only to the server and to auditors you trust with that.
- [ ] **`metadata.pii`** on the datasets that hold personal data. The API masks
      those columns (`••••`) in previews, failing rows and stream rows for
      roles without `data.read.pii` (operator, viewer), and refuses them a check
      or rule that names one. Rows of a protected environment (`prod`) take
      `data.read.protected` (operator, admin), in the preview and as files (the
      file API, git diffs, blame); changing those files takes
      `data.write.protected` (admin); deleting that environment's quality
      reports takes `pipeline.execute.protected` (operator, admin). Snapshot-test
      fixtures and AI proposals measured there take `data.read.protected`;
      fixtures write `metadata.pii` columns as stand-ins of the same kind. A
      protected run's logs, errors and diagnosis stay visible to whoever sees the
      run (they may quote data: keep `print(df)` out of prod code). With auth on,
      each read of a protected environment's rows, files or run output, and each
      unmasked read of PII, is written to `.ducta/audit.log` (`data_reads`).
      `ducta check` warns of a `metadata.pii` column the dataset does not state.
      Promoting a model to Production takes
      `model.promote.production` (admin). Permissions are global, not per
      project: a role reads every project in the workspace.
- [ ] **`DATABASE_URL`** pointing at PostgreSQL rather than SQLite whenever
      accounts are on (above) or `WORKERS > 1`; SQLite has no concurrent writers.
      Several workers also split runs, logs and schedules, which live in each
      process's memory: prefer one worker.
- [ ] **A reverse proxy terminating TLS.** Ducta speaks plain HTTP; a JWT over
      HTTP is a JWT in the clear.
- [ ] **Authentication on even when bound to loopback**, if anything proxies or
      port-forwards to it. The startup warning only sees `HOST`; it cannot know
      what sits in front of the process.
