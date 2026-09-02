# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through
[GitHub Security Advisories](https://github.com/faustinolopezramos/ducta/security/advisories/new),
or by email to <faustinolopezramos@gmail.com> with `SECURITY` in the subject.

Useful things to include, as far as you have them: the affected version, the
extras installed (`api`, `spark`, …), whether authentication was enabled, and
the smallest reproduction you can manage. A proof-of-concept helps but is not
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
| 0.1.x | ✅ |
| < 0.1.1 | ❌ — upgrade; `0.1.1` carries security fixes |

## Threat model

It matters which of these you are running, because they have very different
exposure.

**The CLI and the engine** (`ducta start`, `ducta certify`, the `core`,
`gate`, `check`, `stream`, `mlrun`, `setting` modules) run *your* configuration
and *your* Python on *your* machine. Configuration is code here: `nodes.yaml`
points at Python functions, business rules are evaluated expressions, and
`.py` config files execute on load. Ducta does not sandbox any of that, and is
not trying to. **Treat a Ducta project directory with exactly the trust you
would give a repository of Python scripts** — because that is what it is.

**The API server** (`ducta server start`, the `api` module and the web app)
*is* a security boundary, and is the part this policy is really about. It can
read and write files in the workspace, execute pipelines, run git operations,
and — when explicitly enabled — hand out a shell.

### In scope

- Authentication or authorization bypass on any API route.
- Path traversal out of the workspace root.
- SSRF via git clone sources, or injection into the JDBC gateway.
- Bypassing the SQL sanitizer (`ducta.gate.sql`) or the business-rule
  expression validator (`ducta.check.checks.business`).
- Cross-origin access to the API from a web page (CORS, WebSocket origin).
- Certificate forgery against a *signed* certificate — see below.
- Credentials leaking into logs, argv, certificates, or error responses.

### Out of scope

- **Arbitrary code execution through project configuration.** A node's
  `module`/`function`, a `.py` config file, and a Python business rule all
  execute by design. This is the documented model, not a vulnerability.
- **Forging an unsigned run certificate.** `certificate_hash` is a keyless
  SHA-256: it detects corruption, not a motivated editor, who can recompute it.
  Set `DUCTA_CERTIFICATE_KEY` for tamper-evidence — a forgery against a signed
  certificate *is* in scope.
- **Anything reachable only because the terminal was enabled.**
  `TERMINAL_ENABLED=true` grants shell access on purpose; that is the feature.
- Findings that require an attacker to already have local filesystem or
  process access on the host.
- Vulnerabilities in dependencies with no Ducta-specific exploit path. Report
  those upstream; tell us if Ducta's usage makes them exploitable.

## Production checklist

The API is **local-first by default**: it binds to `127.0.0.1` and ships with
authentication off, so that `ducta server start` works on a laptop with no
setup. Every item below is what you must change before it is reachable by
anyone else. `environment=production` enforces the first three at startup and
refuses to boot otherwise.

- [ ] **`ENVIRONMENT=production`.** This is the switch that turns the rest into
      enforced invariants rather than advice.
- [ ] **`AUTH_ENABLED=true`.** Without it every route — including pipeline
      execution — is unauthenticated.
- [ ] **`JWT_SECRET_KEY`** set to a high-entropy random value
      (`python -c 'import secrets; print(secrets.token_urlsafe(64))'`). Never
      the shipped default.
- [ ] **`DEBUG` unset or false.** Debug mode returns full tracebacks, source
      and local variables on any unhandled exception.
- [ ] **`CORS_ORIGINS`** listing only the origins that must reach the API.
      Never `*`: with credentials allowed, that lets any site a user visits
      read authenticated responses. Loopback is no defence — the browser is on
      the loopback host.
- [ ] **`RATE_LIMIT_ENABLED=true`** (auto-enabled with auth, but set it
      explicitly), and `RATE_LIMIT_REDIS_URL` if you run more than one worker —
      the in-memory limiter is per-process, so the effective limit otherwise
      multiplies by `WORKERS`.
- [ ] **`GIT_CLONE_ALLOWED_HOSTS`** restricted to the forges you actually clone
      from. Outside development this defaults to the public forges; widen it
      deliberately, never to everything.
- [ ] **`TERMINAL_ENABLED`** left off unless you genuinely need a browser
      shell. It is arbitrary command execution on the host by design.
- [ ] **`DUCTA_CERTIFICATE_KEY`** set, if run certificates are meant to be
      evidence rather than checksums.
- [ ] **`DATABASE_URL`** pointing at PostgreSQL rather than SQLite when
      `WORKERS > 1`; SQLite has no concurrent writers.
- [ ] **A reverse proxy terminating TLS.** Ducta speaks plain HTTP; a JWT over
      HTTP is a JWT in the clear.
- [ ] **Authentication on even when bound to loopback**, if anything proxies or
      port-forwards to it. The startup warning only sees `HOST`; it cannot know
      what sits in front of the process.
