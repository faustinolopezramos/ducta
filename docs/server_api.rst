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

**Common Options** (``ducta server start`` and ``ducta ui`` accept the same options):

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

.. list-table::
   :widths: 34 66
   :header-rows: 1

   * - Resource
     - What it does
   * - ``/health``, ``/health/ready``, ``/health/platform``
     - Liveness/readiness probes and platform info (no auth, no ``/api`` prefix).
   * - ``/api/auth``
     - Login, logout, token refresh and the current user (JWT).
   * - ``/api/workspace``
     - Connect a workspace (local path or Git URL), auto-detect, browse
       directories; ``/api/workspace/files`` lists its files.
   * - ``/api/projects``
     - Projects and their pipelines: create, import, update, delete; execute,
       preflight and sweep a pipeline; its datasets, dependencies and node
       schemas; ``GET .../pipelines/{name}/ml-plan?env=`` says what each ML node is
       given (the same answer as ``ducta config show --ml``), and for a serving
       node, ``model_resolution``: the registered version its stage names right now.
       The editor, inspector, alerts and governance endpoints under
       ``/api/projects/{id}`` are described in `Editing and inspecting a project`_.
   * - ``/api/nodes``
     - Nodes of the workspace, their Python code, and their execution history.
   * - ``/api/configs``, ``/api/environments``
     - A project's settings and catalog per environment, and the environments
       it declares.
   * - ``/api/executions``
     - List, inspect, cancel, retry and bulk-cancel executions; their logs and
       errors. Live logs over WebSocket at ``/api/ws/logs/{execution_id}``.
       ``GET .../{id}/diagnosis`` says why a run failed — the kind of failure,
       where, and what changed since the last good run; ``POST .../{id}/resume``
       continues a run paused at a data breakpoint.
       ``GET /api/executions/{id}/streaming`` is the live state of a streaming or
       hybrid run: per pipeline its status and uptime, per node its query's state
       (``active``, ``failed``, ``skipped``, ``stopped``), the latest batch's
       throughput and the model it scores with. ``active`` turns false once the
       run holds no engine.
   * - ``/api/projects/{id}/certificates``, ``/api/certificates/verify``
     - Run Certificates: list, show, verify, diff and reproduce; verify an
       uploaded certificate.
   * - ``/api/quality``
     - Checks, reports, trends and scores; run checks; validate a node's
       quality configuration. ``GET /api/quality/checks`` describes each check:
       its description, default severity and parameters (as JSON Schema);
       ``GET /api/quality/summary`` is the per-dataset overview (latest status and
       score trend).
   * - ``/api/mlops``
     - Experiments and runs, the model registry, promotion and garbage
       collection. Each model lists the project nodes that serve it
       (``served_by``); each version its stage, metrics, features and artifact
       hash.
   * - ``/api/schedules``
     - Cron schedules for pipelines.
   * - ``/api/ingestion``
     - Database connections for ``kind: ingest`` nodes.
   * - ``/api/templates``
     - List templates and generate a project into ``projects/``.
   * - ``/api/git``
     - The workspace repository: status, branches, history, diffs (including the
       uncommitted working diff and a file at any commit), blame, commit, pull/push,
       revert.

Projects and configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~

The API reads and writes the same files the CLI runs (:doc:`configuration`). A
workspace is either one project (``ducta.yaml`` at its root) or a directory
whose ``projects/<id>/`` sub-directories are projects. A project's description,
variables and timestamps live in its ``ducta.yaml`` (``description`` and
``metadata``).

Every write — a node, a pipeline, settings or a catalog entry — edits the YAML
in place, keeping comments and key order, and is validated against every
environment before it is kept: an edit that would make any environment invalid
is refused with the problems, and the files are left untouched. Saving does
**not** commit: committing is the user's call, from the web app's Changes panel
or with git itself. The optimistic-concurrency token is a hash of the file's
content (still returned as ``commit_sha`` for compatibility): send back the one
you read — ``expected_commit_sha`` for nodes and configs, ``expected_sha`` for
pipelines — and a change someone else saved in between, committed or not,
answers ``409`` instead of being overwritten.

Editing and inspecting a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These are what the web app's editor and inspector use; all live under
``/api/projects/{id}``. None of them imports project code unless it says so,
and none commits.

.. list-table::
   :widths: 38 62
   :header-rows: 1

   * - Endpoint
     - What it does
   * - ``POST .../validate``
     - Validates the project *with unsaved edits*, without writing: the format-2
       loader in every environment, then each node's ``run:`` against its
       function's signature (from the syntax tree). Every problem carries file,
       line, node and, when there is one, a fix.
   * - ``GET``/``PUT .../pipelines/{name}/source``
     - A pipeline's YAML as written; replacing it keeps the file only if the
       whole project still validates.
   * - ``POST .../pipelines/{name}/ops``
     - Canvas edits (connect a dataset, add or remove a node, set a key) applied
       in place; the response carries the inverse operations for undo.
   * - ``POST .../pipelines/{p}/nodes/{n}/extract-template``,
       ``POST .../pipelines/{p}/extract-subpipeline``
     - Move a node into ``templates/nodes/`` (``use``/``with``) or several nodes
       into ``templates/pipelines/`` (``use: pipeline:<name>``), in one validated
       transaction. ``GET .../templates/nodes`` and ``.../templates/pipelines``
       list them. See ADR 0001 in ``docs/adr/``.
   * - ``GET .../schema``, ``.../locations``, ``.../code-index``, ``.../ruff-config``
     - Editor support: the format-2 JSON Schema; where each dataset, pipeline and
       node is written (file:line, for go-to-definition); which function each node
       runs and where; the project's Ruff settings.
   * - ``GET .../lsp``, ``GET .../debugger``
     - Whether a Python language server is available (``LSP_COMMAND``) and whether
       a run can be debugged. The editor talks to them over WebSockets at
       ``/api/projects/{id}/lsp`` and ``/api/projects/{id}/debug``.
   * - ``GET .../pipelines/{name}/nodes/{node}/effective-config``,
       ``GET .../environments/compare``
     - A node's settings per environment and where each comes from; every
       effective value side by side across environments.
   * - ``GET .../datasets/{dataset}/preview``
     - Columns and first rows of a dataset as materialized in ``env``.
   * - ``GET .../pipelines/{p}/nodes/{n}/column-lineage``
     - Source columns for each column an ingest node writes (parsed from its SQL
       with sqlglot). Python transforms are not analysed.
   * - ``POST .../quality/try``, ``POST .../quality/failing-rows``
     - Run a draft quality block on a dataset's data without saving anything; the
       rows a row-level check fails on.
   * - ``GET .../nodes/{n}/tests``, ``POST .../nodes/{n}/tests/snapshot``,
       ``POST .../tests/run``
     - The tests that cover a node; write a snapshot test from its materialized
       inputs; run the tests with pytest (runs project code, so it needs
       ``pipeline.execute``).
   * - ``GET .../staleness``, ``GET .../pipelines/{name}/last-success``
     - Which nodes changed since their pipeline's last successful run (from the
       source and the run certificates); that last success and its commit.
   * - ``GET .../metrics``
     - Runs, success rate, p50/p95 duration and SLA freshness per pipeline and
       node, from the run certificates.
   * - ``.../comments``
     - Comment threads on nodes and lines of code: list, start, reply,
       resolve/reopen, delete. Stored as ``.ducta/comments/<id>.json``, meant to be
       committed with the project.
   * - ``GET .../alerts``, ``POST .../alerts/test``, ``POST .../alerts/check``
     - The ``alerts:`` rules of ``ducta.yaml``; send a test message; alert on
       pipelines late for their ``metadata.sla`` — call it from a schedule, or set
       ``SLA_CHECK_MINUTES``.
   * - ``GET .../governance``
     - Protected environments (``governance.protected_environments``, default
       ``[prod, production]``) and whether the current user may run in them —
       that takes ``pipeline.execute.protected`` (operator, admin).

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
authentication is disabled, and persistence is
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

.. _roles-and-permissions:

Roles and permissions
---------------------

With ``AUTH_ENABLED=true`` each route checks one permission, granted by the user's
roles. With authentication off every request runs as a local admin.
``GET /api/auth/me`` returns the user's ``roles`` and ``permissions`` (``["*"]`` for an
admin), and the UI hides or disables what the user may not do. The server enforces
the permissions regardless.

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Role
     - Permissions
   * - ``admin``
     - ``*`` (everything).
   * - ``developer``
     - Read and write on workspace, configs, pipelines, nodes, datasets, Git,
       repositories, executions, projects, quality, ingestion and templates;
       ``pipeline.execute``, ``quality.run``, ``git.revert``, ``model.promote`` and
       ``model.delete``.
   * - ``viewer``
     - Read only: ``workspace.read``, ``project.read``, ``config.read``,
       ``pipeline.read``, ``node.read``, ``dataset.read``, ``git.read``,
       ``repository.read``, ``execution.read``, ``quality.read``,
       ``ingestion.read``, ``template.read``.

Some routes need more than their name suggests:

- **Preflight** (``POST .../pipelines/{name}/preflight``) needs
  ``pipeline.execute``. Its deep check imports the project's modules, and
  importing a module runs its top-level code.
- **A Git URL as source** (``?source=`` / ``X-Source-Path``, or
  ``POST /api/workspace/select``) needs ``repository.write``, because the server
  clones it. The operator's ``DUCTA_WORKSPACE`` is not checked.
- **Models**: promoting a version needs ``model.promote``. Deleting a version, and
  the garbage collection that deletes old ones, needs ``model.delete``.
- **Testing an unsaved ingestion connection** needs ``ingestion.write``. The
  server connects to whatever host and port the caller sends.

A test (``tests/api/test_rbac.py``) walks every route and fails if a route that
writes is reachable by a viewer, so a new route cannot ship without a permission.

See ``SECURITY.md`` in the repository root for the vulnerability-reporting
process and the same hardening guidance in checklist form.
