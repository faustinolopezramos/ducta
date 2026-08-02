Ducta Server & API
==================

Ducta includes a built-in FastAPI server that provides a RESTful interface for managing projects, executing pipelines, and monitoring your data platform through a visual dashboard.

Features
--------

- **REST API**: Programmatic control over your Ducta workspace.
- **Visual Dashboard**: A React-based UI for monitoring pipeline health and execution history.
- **Persistence**: Optional SQLite/PostgreSQL backend for long-term metadata storage, configured via the ``DATABASE_URL`` environment variable (e.g. ``sqlite+aiosqlite:///./data/ducta.db`` or ``postgresql+asyncpg://user:pass@host:5432/ducta``). When unset, the API runs in in-memory mode.
- **Interactive Docs**: Built-in Swagger/OpenAPI documentation.
- **Authentication**: JWT-based security for enterprise environments.

Starting the Server
-------------------

You can start the server directly from the CLI:

.. code-block:: bash

   # Start the API server only
   ducta server start --port 8000

   # Launch the full UI (Dashboard + API)
   ducta ui --port 8000

**Common Options** (``ducta server start`` and ``ducta ui`` accept the same core options; ``ducta ui`` additionally has ``--enable-terminal``):

- ``--port``: Port to bind (default: 8000). No short flag.
- ``--host``: Host to bind (default: 127.0.0.1).
- ``--source``: Workspace source path or Git URL to load automatically.
- ``--db``: Path to the SQLite database used for the local execution-history store (default: ``~/.ducta/executions.db``). This is separate from the optional ``DATABASE_URL``-configured backend described below.
- ``--no-browser``: Don't open the browser automatically.

API Endpoints
-------------

Once the server is running, you can access the interactive documentation at ``http://localhost:8000/docs`` (Swagger UI) or ``http://localhost:8000/redoc`` (ReDoc). The raw OpenAPI schema is served at ``http://localhost:8000/openapi.json``.

All domain routes are mounted under the ``/api`` prefix (there is no ``/v1`` version segment). Health probes are mounted without the ``/api`` prefix.

Key API resources:

- ``/health``, ``/health/ready``, ``/health/platform``: Liveness/readiness probes and platform info (no auth, no ``/api`` prefix).
- ``/api/auth``: Login, logout, token refresh, and current-user info (JWT-based).
- ``/api/workspace``, ``/api/connect``: Resolve and validate a workspace source (local path or Git URL).
- ``/api/projects``: Manage projects and their pipelines, including triggering pipeline execution.
- ``/api/nodes``: Manage workspace-scoped node definitions.
- ``/api/configs``, ``/api/environments``: Read/update workspace config files and environments.
- ``/api/executions``: List, inspect, cancel executions and stream logs (also exposes streaming-pipeline status/metrics/checkpoints sub-resources); live log tailing is available over WebSocket at ``/api/ws/logs/{execution_id}``.
- ``/api/git``, ``/api/repository``: Git history and remote repository adapters.
- ``/api/workspace/files``: Browse workspace files.

There is currently no ``/api/quality`` or ``/api/mlops`` REST resource — data quality and MLOps registry/experiment data are accessed via the ``ducta quality`` and ``ducta experiment``/``ducta model`` CLI commands (see :doc:`cli_usage`), not the HTTP API.

Integration
-----------

The Ducta API can be integrated into your existing CI/CD or orchestration tools (like Airflow or Prefect) to trigger pipelines remotely. Pipeline execution is triggered per-project, per-pipeline:

.. code-block:: bash

   curl -X POST "http://localhost:8000/api/projects/<project_id>/pipelines/sales_etl/execute" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer <access_token>" \
        -d '{"env": "prod"}'

The request body accepts ``env`` (default ``"base"``), ``node_name``, ``dry_run``, ``validate_only``, ``start_date``, and ``end_date``. The endpoint returns ``202 Accepted`` with an execution record (``id``, ``status``, etc.) that can be polled via ``GET /api/executions/{execution_id}``.

Deployment Model
----------------

The Ducta API server is designed as a **single-node service**. Understanding
this model is important before you put it behind a load balancer or scale it out:

- **Execution state is per-process and in-memory.** The ``ExecutionManager``
  keeps running executions, their logs, the concurrency queue
  (``MAX_CONCURRENT_EXECUTIONS``, default 5), the rate-limit counters, and the
  pipeline schedules inside the worker process. There is no distributed queue
  (Celery/RQ) or shared execution broker.
- **Pipelines run in-process** on the API host (a fresh subprocess is used only
  for preflight validation). The API host therefore needs the runtime
  dependencies (Spark, drivers) of the pipelines it runs.
- **Multiple workers fragment state.** Running ``uvicorn`` with ``WORKERS > 1``
  gives each worker its own in-memory state, so executions, rate limits, and
  schedules are not shared across workers. For this reason the background
  scheduler is automatically disabled when ``WORKERS > 1``, and SQLite is
  rejected with ``WORKERS > 1``.

**Recommended topology:** run a single API process (``WORKERS=1``) per node,
front it with a TLS-terminating reverse proxy, and configure a persistent
database (see below) so execution history survives restarts. To scale
throughput, scale the underlying compute (e.g. a Spark cluster / Databricks)
rather than the API process, and raise ``MAX_CONCURRENT_EXECUTIONS``.

.. _secure-startup-checklist:

Secure Startup Checklist
------------------------

The API ships with **safe local-first defaults**: it binds to ``127.0.0.1``,
authentication is disabled, the terminal is disabled, and persistence is
in-memory. These defaults make local development frictionless but are **not**
appropriate once the service is reachable by anyone else.

When exposing the API beyond ``localhost``, set ``ENVIRONMENT=production`` — this
turns the two most important checks below into hard startup errors instead of
warnings — and work through this checklist:

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Setting
     - Recommended
     - Why
   * - ``ENVIRONMENT``
     - ``production``
     - Enforces ``AUTH_ENABLED=true`` and a non-default ``JWT_SECRET_KEY``.
   * - ``AUTH_ENABLED``
     - ``true``
     - Requires a valid JWT for every domain endpoint. Off by default. The
       server logs a loud ``SECURITY`` warning at startup if auth is off while
       bound to a non-local host.
   * - ``JWT_SECRET_KEY``
     - strong random value
     - Signs access tokens. The default ``change-me-in-production`` is refused
       in production.
   * - ``CORS_ORIGINS``
     - explicit allow-list
     - Avoid ``*``. Wildcard origins with credentials are rejected outside
       development.
   * - ``TERMINAL_ENABLED``
     - ``false``
     - Grants arbitrary shell execution on the host. Keep off unless every
       authenticated user is fully trusted.
   * - ``RATE_LIMIT_ENABLED``
     - ``true``
     - Enables the in-process sliding-window limiter. Also put a WAF / proxy
       rate limit in front.
   * - ``DATABASE_URL``
     - PostgreSQL DSN
     - Persists executions, logs, and users. Empty (default) means in-memory —
       state is lost on restart. Use ``postgresql+asyncpg://...`` for anything
       shared or long-lived.
   * - ``HOST``
     - ``127.0.0.1`` behind a proxy
     - Only bind a public interface intentionally, and terminate TLS in a
       reverse proxy in front of the app.

See ``SECURITY.md`` in the repository root for the vulnerability-reporting
process and the same hardening guidance in checklist form.
