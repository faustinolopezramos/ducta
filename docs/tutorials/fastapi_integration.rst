FastAPI Integration
===================

This tutorial shows how to wrap your Ducta project in a REST API using FastAPI. This allows you to trigger pipelines, check their status, and get results via HTTP requests, which is useful for integrating with web applications or other services.

**Why use FastAPI with Ducta?**

- **Remote Execution**: Trigger pipelines from anywhere, without direct access to the machine.
- **Service Integration**: Allow other microservices to run and interact with your data pipelines.
- **UI Integration**: Provide a backend for a web-based user interface that can start and monitor pipelines.

A Basic Pipeline API
--------------------

Ducta includes a built-in API that you can use or extend. However, if you want to build your own custom integration, you should use the core ``ExecutionManager`` and ``WorkspaceManager``.

**Project Setup**

1.  Install Ducta with API extras:
    .. code-block:: bash

       pip install ducta[api] uvicorn

2.  Save the following code as ``api_demo.py``.

**API Code (``api_demo.py``)**

.. code-block:: python

   import asyncio
   from pathlib import Path
   from fastapi import FastAPI, HTTPException, Depends
   from ducta.api.execution.manager import ExecutionManager
   from ducta.api.workspace.manager import WorkspaceManager
   from ducta.api.models.execution import ExecuteRequest

   app = FastAPI(title="Custom Ducta API")

   # --- Dependency Injection ---
   # In a real app, use a singleton or a proper dependency container
   EXEC_MANAGER = ExecutionManager()
   PROJECT_ROOT = Path("./my_project")

   @app.post("/run/{pipeline_name}")
   async def run_pipeline(pipeline_name: str, body: ExecuteRequest):
       """
       Trigger a Ducta pipeline execution asynchronously.
       """
       workspace = WorkspaceManager(PROJECT_ROOT)

       # 1. Validate that the pipeline exists in the workspace
       ctx = workspace.load_context(body.env)
       from ducta.exec.executor import PipelineExecutor
       executor = PipelineExecutor(ctx)

       if not executor.validate_pipeline(pipeline_name):
           raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_name} not found")

       # 2. Trigger execution via the manager
       # This runs in a background thread and returns an execution object immediately
       execution = EXEC_MANAGER.execute(
           source_path=PROJECT_ROOT,
           pipeline_name=pipeline_name,
           env=body.env,
           start_date=body.start_date,
           end_date=body.end_date
       )

       return {
           "execution_id": execution.id,
           "status": execution.status,
           "message": f"Pipeline {pipeline_name} started successfully"
       }

   @app.get("/status/{execution_id}")
   async def get_status(execution_id: str):
       """
       Check the status of a specific execution.
       """
       try:
           execution = EXEC_MANAGER.get_execution(execution_id)
           return execution
       except Exception:
           raise HTTPException(status_code=404, detail="Execution not found")

How to Run
----------

1.  Initialize a project:
    .. code-block:: bash

       ducta template --template medallion_basic --project-name my_project

2.  Start your custom API:
    .. code-block:: bash

       uvicorn api_demo:app --reload

3.  Trigger a run:
    .. code-block:: bash

       curl -X POST "http://localhost:8000/run/etl" \\
            -H "Content-Type: application/json" \\
            -d '{"env": "dev"}'

What's Next?
------------

- **Authentication**: Integrate OAuth2 or JWT to secure your endpoints.
- **Monitoring**: Use WebSockets to stream logs in real-time from the ``ExecutionManager``.
- **Persistence**: Configure a database (SQLite or PostgreSQL) in Ducta to store execution history.
