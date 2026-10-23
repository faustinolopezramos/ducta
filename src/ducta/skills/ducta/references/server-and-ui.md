# The web UI and the API server

Needs `pip install "ducta[api]"`.

```bash
ducta ui --source /path/to/project        # web app + API, opens the browser
ducta server start --port 8000 --no-browser
```

Options for both: `--port` (8000), `--host` (127.0.0.1), `--source PATH_OR_GIT_URL`,
`--no-browser`, `--db PATH` (execution history, default `~/.ducta/executions.db`).
`ducta ui --enable-terminal` adds a web shell — it grants arbitrary command execution to
logged-in users; never enable it unless the user insists and understands that.

- Swagger: `http://localhost:8000/docs`; OpenAPI: `/openapi.json`.
- Routes live under `/api` (no version segment); health probes at `/health`.
- A workspace is one project (`ducta.yaml` at its root) or a folder whose
  `projects/<id>/` are projects.

## What the web app does

Projects and pipelines (canvas and YAML editor), the catalog, runs with live logs,
quality reports, the model registry, run certificates, Git (status, diff, commit),
ingestion connections, schedules, and the AI builder (see [ai-builder](ai-builder.md)).
Every save edits the YAML in place (comments kept) and is validated against every
environment first; **saving never commits** — committing is the user's action.

## Security: before exposing it beyond localhost

Defaults are local-first: bound to 127.0.0.1, **authentication off**, history in memory
or SQLite. Before anyone else can reach it:

| Variable | Set to |
|---|---|
| `ENVIRONMENT` | `production` (turns the checks below into startup errors) |
| `AUTH_ENABLED` | `true` |
| `JWT_SECRET_KEY` | a long random value (never the default) |
| `DUCTA_ADMIN_PASSWORD` | the `admin` user's password; required in production, `admin` is refused |
| `CORS_ORIGINS` | an explicit list, not `*` |
| `RATE_LIMIT_ENABLED` | `true` |
| `DATABASE_URL` | `postgresql+asyncpg://…` for shared/persistent history |
| `HOST` | `127.0.0.1` behind a TLS reverse proxy |

Run **one** API process (`WORKERS=1`): execution state, schedules and rate limits live in
memory per process. Scale the compute (Spark/Databricks), not the API.

## Roles and permissions (with `AUTH_ENABLED=true`)

| Role | Can |
|---|---|
| `admin` | everything (`*`), including AI settings (`ai.configure`) |
| `developer` | read/write projects, pipelines, configs, Git, quality, ingestion; run pipelines; promote/delete models; use AI (`ai.use`) |
| `operator` | read, and run pipelines including protected environments (`pipeline.execute.protected`) |
| `viewer` | read only |

`GET /api/auth/me` returns a user's roles and permissions. Running in a protected
environment (`governance.protected_environments`, default `[prod, production]`) needs
`pipeline.execute.protected`.

## Triggering runs from other tools

```bash
curl -X POST "http://localhost:8000/api/projects/<project_id>/pipelines/<pipeline>/execute" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"env": "dev", "start_date": "2026-01-01", "end_date": "2026-01-31"}'
```

Returns `202` with an execution id; poll `GET /api/executions/{id}`;
`GET /api/executions/{id}/diagnosis` explains a failure.

## Common problems

| Symptom | Fix |
|---|---|
| `ducta ui` fails with missing modules | `pip install "ducta[api]"` |
| port already in use | `--port 8010`, or stop the other process |
| the UI shows no project | start with `--source /path/to/project`, or select the workspace in the app |
| a save is refused with problems | the edit would make some environment invalid: fix what it lists |
| startup refuses in production | set `AUTH_ENABLED=true`, a real `JWT_SECRET_KEY` and a `DUCTA_ADMIN_PASSWORD` (not `admin`) |
| SQLite rejected | it is refused with `WORKERS > 1`: keep one worker or use PostgreSQL |
