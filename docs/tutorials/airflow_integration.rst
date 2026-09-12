Airflow Integration
===================

This tutorial demonstrates how to orchestrate your Ducta pipelines using Apache Airflow. By combining Ducta and Airflow, you can build robust, scheduled, and scalable data workflows.

**Benefits of using Ducta with Airflow:**

- **Decoupling**: Your core business logic resides in your Ducta project, completely independent of Airflow. The Airflow DAGs are only responsible for triggering the pipelines.
- **Simplicity**: The Airflow DAGs remain simple and clean. All the complexity of data sources, transformations, and destinations is managed by Ducta's configuration.
- **Testability**: You can easily test your Ducta pipelines locally without needing an Airflow environment.

A Basic ETL DAG
---------------

Here is an example of an Airflow DAG that runs a sequence of Ducta pipelines for a typical Bronze-Silver-Gold ETL process.

Each task in the DAG corresponds to a Ducta pipeline. When a task runs, it invokes the Ducta library, executes the specified pipeline, and reports success or failure back to Airflow.

.. code-block:: python

   from airflow import DAG
   from airflow.operators.python import PythonOperator
   from datetime import datetime, timedelta
   from ducta import PipelineExecutor, ContextLoader

   # Define the path to your Ducta project directory
   # In a real Airflow deployment, this would be a fixed path on your Airflow worker nodes
   # where your Ducta project is deployed.
   PROJECT_PATH = "/path/to/your/ducta_project"

   CONFIG_PATHS = {
       "global_config": f"{PROJECT_PATH}/config/base/global_config.toml",
       "pipelines": f"{PROJECT_PATH}/config/base/pipelines.toml",
       "nodes": f"{PROJECT_PATH}/config/base/nodes.toml",
       "input": f"{PROJECT_PATH}/config/base/input.toml",
       "output": f"{PROJECT_PATH}/config/base/output.toml",
   }

   default_args = {
       'owner': 'data-team',
       'depends_on_past': False,
       'start_date': datetime(2024, 1, 1),
       'email_on_failure': False,
       'email_on_retry': False,
       'retries': 1,
       'retry_delay': timedelta(minutes=5),
   }

   def run_ducta_pipeline(pipeline_name: str, ds: str):
       """
       A generic Python callable that executes a Ducta pipeline.
       """
       print(f"Executing Ducta pipeline: {pipeline_name} for date {ds}")

       # 1. Load the production context from your Ducta project
       context = ContextLoader().load_from_paths(CONFIG_PATHS, env="production")

       # 2. Initialize the executor
       executor = PipelineExecutor(context)

       # 3. Run the pipeline for a specific date.
       #    run_pipeline raises on failure, which Airflow records as a task
       #    failure automatically -- no manual success check is needed.
       executor.run_pipeline(
           pipeline_name,
           start_date=ds,
           end_date=ds,
       )

       print(f"✅ Ducta pipeline '{pipeline_name}' completed successfully.")

   with DAG(
       dag_id='ducta_daily_etl',
       default_args=default_args,
       description='Daily ETL DAG to run Ducta pipelines for Bronze, Silver, and Gold layers.',
       schedule_interval='0 2 * * *',  # Runs daily at 2 AM
       catchup=False,
       tags=['ducta', 'etl'],
   ) as dag:

       run_load_pipeline = PythonOperator(
           task_id='run_load_pipeline',
           python_callable=run_ducta_pipeline,
           op_kwargs={'pipeline_name': 'load', 'ds': '{{ ds }}'},
       )

       run_transform_pipeline = PythonOperator(
           task_id='run_transform_pipeline',
           python_callable=run_ducta_pipeline,
           op_kwargs={'pipeline_name': 'transform', 'ds': '{{ ds }}'},
       )

       run_aggregate_pipeline = PythonOperator(
           task_id='run_aggregate_pipeline',
           python_callable=run_ducta_pipeline,
           op_kwargs={'pipeline_name': 'aggregate', 'ds': '{{ ds }}'},
       )

       # Define the task dependencies
       run_load_pipeline >> run_transform_pipeline >> run_aggregate_pipeline

How it Works
------------

1.  **`PROJECT_PATH`**: You must define the absolute path to your deployed Ducta project. Your Airflow workers need access to this directory.

2.  **`run_ducta_pipeline` function**: This is the core of the integration. It's a `PythonOperator` callable that:
    - Loads the Ducta context for your `production` environment via `ContextLoader().load_from_paths(...)`.
    - Runs a specific pipeline with `PipelineExecutor.run_pipeline(...)`, passing in the execution date (`ds`) from Airflow as `start_date`/`end_date`.
    - Lets any exception raised by `run_pipeline` propagate, which Airflow automatically records as a failed task.

3.  **DAG Definition**: The DAG itself is standard Airflow code. We define three `PythonOperator` tasks, one for each of our `load`, `transform`, and `aggregate` pipelines.

4.  **Task Dependencies**: We use `>>` to set the execution order, ensuring that the `load` pipeline runs before `transform`, and `transform` runs before `aggregate`.

Next Steps
----------

- **Deploy**: Place your Ducta project in a directory accessible to your Airflow workers and update `PROJECT_PATH`.
- **Customize**: Modify the `pipeline_name` in the `op_kwargs` to match your project's pipelines.
- **Note on scheduling**: Ducta itself has no built-in scheduler. All cron-style scheduling (`schedule_interval` above) and cross-pipeline ordering must come from Airflow (or another external orchestrator) -- Ducta only executes the pipeline you ask it to run when invoked.
