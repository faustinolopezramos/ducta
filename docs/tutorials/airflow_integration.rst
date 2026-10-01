Airflow Integration
===================

This tutorial demonstrates how to orchestrate your Ducta pipelines using Apache Airflow. By combining Ducta and Airflow, you can build robust, scheduled, and scalable data workflows.

**Benefits of using Ducta with Airflow:**

- **Decoupling**: Your core business logic resides in your Ducta project, completely independent of Airflow. The Airflow DAGs are only responsible for triggering the pipelines.
- **Simplicity**: The Airflow DAGs remain simple and clean. All the complexity of data sources, transformations, and destinations is managed by Ducta's configuration.
- **Testability**: You can easily test your Ducta pipelines locally without needing an Airflow environment.

Two ways to run a pipeline
--------------------------

**Run the CLI** (``BashOperator``) when Airflow workers only need to *start*
work — Ducta runs in its own process with its own environment, and the exit
code tells Airflow what happened.

**Call Ducta in-process** (``PythonOperator``) when the worker has Ducta and
Spark installed and you want the run's result object in the task.

With the CLI
------------

.. code-block:: python

   from datetime import datetime, timedelta

   from airflow import DAG
   from airflow.operators.bash import BashOperator

   PROJECT = "/opt/pipelines/sales"          # a Ducta project deployed on the workers

   with DAG(
       dag_id="sales_daily",
       start_date=datetime(2026, 1, 1),
       schedule="0 2 * * *",
       catchup=True,                         # backfills are safe: re-runs are idempotent
       default_args={"retries": 2, "retry_delay": timedelta(minutes=10)},
   ) as dag:
       daily = BashOperator(
           task_id="daily",
           bash_command=(
               "ducta start --base-path {{ params.project }} --env prod --pipeline daily "
               "--start-date {{ ds }} --end-date {{ ds }}"
           ),
           params={"project": PROJECT},
       )

A non-zero exit fails the task. Exit code ``7`` means another run holds the
lock on an output — nothing ran — so an Airflow retry is exactly right; with
``settings.run_lock.on_conflict: wait`` Ducta waits for the lock itself.

In-process
----------

.. code-block:: python

   from datetime import datetime

   from airflow import DAG
   from airflow.operators.python import PythonOperator

   PROJECT = "/opt/pipelines/sales"


   def run_pipeline(pipeline: str, ds: str) -> str:
       import ducta

       context = ducta.load_project(PROJECT, env="prod")
       result = ducta.PipelineExecutor(context).run_pipeline(
           pipeline, start_date=ds, end_date=ds
       )
       return result.run_id                  # pushed to XCom: the run's certificate id


   with DAG(dag_id="sales_daily_py", start_date=datetime(2026, 1, 1), schedule="@daily") as dag:
       PythonOperator(
           task_id="daily",
           python_callable=run_pipeline,
           op_kwargs={"pipeline": "daily", "ds": "{{ ds }}"},
       )

``run_pipeline`` raises when the pipeline fails, which fails the task.
Relative ``paths`` in the project resolve against the worker's working
directory, so use absolute or cloud paths for ``prod``.

Chains of pipelines
-------------------

Airflow tasks can mirror bronze → silver → gold pipelines one by one, or a
single task can run the chain Ducta already knows: declare
``depends_on: [bronze]`` in the silver pipeline file and start the last
pipeline with ``--reuse-upstream``, which skips any upstream whose outputs are
still valid for the same inputs, dates, code and configuration.

Next steps
----------

- :doc:`/cli_usage` — every option and exit code of ``ducta start``
- :doc:`certificates` — using ``run_id`` to prove what a task did
