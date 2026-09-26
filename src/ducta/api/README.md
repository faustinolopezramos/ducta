# Ducta API

> **The REST + WebSocket server of Ducta.** Built on **FastAPI**, it exposes pipeline configuration, execution, git history, data quality, MLOps, and workspace management over HTTP — and serves the bundled web UI. Sources (local paths or Git URLs) are provided per request, so one server can drive many projects.

## At a glance

| | |
|---|---|
| **Purpose** | Expose Ducta over HTTP/WS for tools, automation, and the web UI |
| **Layer** | Interface (service) |
| **Depends on** | `core`, `setting`, `console`; optional SQLAlchemy persistence |
| **Used by** | `ui` and any external HTTP client |
| **Key entry points** | `create_app()` / `ducta.api.main:app`, routers under `/api`, `ducta server start` |
| **Install** | `pip install "ducta[api]"` |

## Where it fits

```mermaid
flowchart TD
    console["console · CLI"] --> core
    api["api · REST / WebSocket"] --> core
    ui["ui · Web UI"] --> api
    setting["setting · Config foundation"] --> core["core · Orchestration"]
    core --> gate["gate · Data I/O"]
    core --> stream["stream · Streaming"]
    core --> check["check · Data quality"]
    core --> mlrun["mlrun · MLOps"]
    style api fill:#4f46e5,stroke:#312e81,color:#fff
```

---

## 1. Overview

### For Non-Technical Users
Ducta API is the **backend brain** behind the web app and any automation. It lets tools and teammates — not just one person at a terminal — start pipelines, watch them run live, browse configuration, review data-quality results, and manage models, all through a standard web interface with optional login.

### For Technical Users
Ducta API is the service layer, implementing:
*   **App factory & lifespan**: `create_app()` wires middleware, routes, exception handlers, optional DB persistence + migrations, the execution manager, and a config cache; it warns when bound to a non-local address without auth (`main.py`).
*   **Routers under `/api`**: auth, execution (+ WebSocket log streaming), configs, environments, git, repository, projects, nodes, mlops, quality, ingestion, templates, workspace, certificates, connect, plus a `/ws` terminal and unauthenticated health probes (`routes/`).
*   **Optional JWT auth**: `AuthService` (bcrypt password hashing, jose-signed HS256 tokens with type/expiry checks); production settings refuse the default secret and require `auth_enabled` (`auth/`, `config.py`).
*   **Execution engine**: an in-memory `ExecutionManager` with a bounded queue, concurrent-run limits, log buffering, and optional DB-backed persistence layered transparently (`execution/`).
*   **Source resolution with SSRF defense**: per-request local paths are security-validated; Git clones are host-allow-listed and reject internal/non-routable targets (loopback, private, link-local metadata endpoint) (`source/resolver.py`).
*   **Persistence & repositories**: optional SQLAlchemy-async engine, Alembic-style migrations, and repository/store abstractions for projects, nodes, and execution history (`db/`, `repositories/`, `repository/`).
*   **Middleware**: request-ID tagging, CORS, and configurable per-IP rate limiting (in-memory or Redis) (`middleware/`).

---

## 2. Configuration

Settings come from environment variables (Pydantic `Settings`, `config.py`). Key variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address (non-local without auth triggers a warning) |
| `ENVIRONMENT` | `development` | `production` enforces auth + a non-default JWT secret |
| `AUTH_ENABLED` | `false` | Require JWT authentication |
| `JWT_SECRET_KEY` | `change-me-in-production` | HS256 signing key (must be overridden in prod) |
| `JWT_EXPIRATION_HOURS` | `24` | Access-token lifetime |
| `DATABASE_URL` | `""` (in-memory) | `sqlite+aiosqlite:///...` or `postgresql+asyncpg://...` |
| `RUNS_DIR` | `~/.ducta/runs` | Where the file-based execution store writes `meta.json` + `logs.jsonl` per run. Empty disables file persistence (memory-only) |
| `RATE_LIMIT_ENABLED` | `false` | Per-IP rate limiting (`RATE_LIMIT_REQUESTS`, `..._WINDOW_SECONDS`, `RATE_LIMIT_REDIS_URL`) |
| `MAX_CONCURRENT_EXECUTIONS` | `5` | Parallel pipeline runs |
| `CORS_ORIGINS` | `["*"]` | Allowed origins |
| `GIT_CLONE_ALLOWED_HOSTS` | `[]` | Allow-list for Git clone hosts (empty = public hosts only, internal blocked) |

**Production checklist**: set `ENVIRONMENT=production`, `AUTH_ENABLED=true`, a strong `JWT_SECRET_KEY`, and either bind to `127.0.0.1` or place the server behind an authenticating proxy.

**Where execution history lives**: the Execution History page reads from two layers merged together — the in-memory `ExecutionStore` (capped by `max_executions_in_memory`, evicted after `execution_retention_seconds`, lost on restart) and the file-based store at `RUNS_DIR` (persists across restarts). Setting `DATABASE_URL` adds a third, queryable layer used for single-run/log lookups once a record has aged out of both memory and `RUNS_DIR`. To fully clear history, delete `RUNS_DIR` (and the `executions`/`execution_logs` tables if `DATABASE_URL` is set) — restarting the server alone only clears memory. This is independent of Data Quality's storage, which lives under `<output_path>/<environment>/.quality` per pipeline config, not under `RUNS_DIR`.

---

## 3. Running the Server

```bash
# Via the CLI (launches this API + serves the UI)
ducta server start --host 127.0.0.1 --port 8000
ducta ui --port 8000            # same server, opens a browser

# Directly with uvicorn
uvicorn ducta.api.main:app --host 127.0.0.1 --port 8000

# Production-style env
export ENVIRONMENT=production
export AUTH_ENABLED=true
export JWT_SECRET_KEY="$(openssl rand -hex 32)"
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/ducta"
uvicorn ducta.api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Interactive docs are served at `/docs` (Swagger) and `/redoc`; the OpenAPI schema at `/openapi.json`.

---

## 4. HTTP Quickstart

All application endpoints are under the `/api` prefix. Sources are passed per request.

### Step 1: Health check (no auth)
```bash
curl http://127.0.0.1:8000/health
```

### Step 2: Authenticate (when AUTH_ENABLED=true)
```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)
```

### Step 3: Connect to a source and inspect configs
```bash
# Resolve a source (local path, or a Git URL to clone)
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/workspace/select -d '{"path_or_url":"/path/to/project"}'

# List configs for an environment
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/configs/dev?source=/path/to/project"
```

### Step 4: Execute a pipeline
```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/projects/{project_id}/pipelines/sales_daily/execute \
  -d '{"env":"dev"}'
```

### Step 5: Manage runs and stream logs
```bash
# List / cancel / retry executions
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/executions
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/executions/{execution_id}/cancel
```
```
# Live log stream over WebSocket
ws://127.0.0.1:8000/api/ws/logs/{execution_id}
```

### Programmatic (ASGI / tests)
```python
from fastapi.testclient import TestClient
from ducta.api.main import app

client = TestClient(app)
assert client.get("/health").status_code == 200
```
