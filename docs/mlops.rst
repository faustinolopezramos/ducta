MLOps & Experiment Tracking
============================

Ducta's MLOps module provides a unified infrastructure for managing the machine learning lifecycle. It focuses on observability, reproducibility, and deployment of models within your data pipelines.

Core Capabilities
-----------------

*   **Experiment Tracking**: Automatic logging of parameters, metrics, and models.
*   **Model Registry**: Centralized management of model versions and lifecycle stages (Staging, Production, Archived).
*   **Artifact Management**: Store models, plots, and datasets securely in cloud storage.
*   **MLflow Integration**: Native support for MLflow as a backend for tracking and registry.

Configuration
-------------

Configure MLOps under the ``mlops`` key of ``config/global_config.{ext}``.
Ducta turns tracking on automatically for ``ml``-type pipelines — you don't call
any setup function in your code.

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Key
     - Default
     - Description
   * - ``backend_type``
     - ``"local"``
     - Storage backend: ``local``, ``databricks``, or ``distributed``.
   * - ``storage_path``
     - ``"./mlops_data"``
     - Root directory for experiments, registry, and artifacts.
   * - ``catalog``
     - ``"main"``
     - Databricks Unity Catalog name (if applicable).
   * - ``schema``
     - ``"ml_tracking"``
     - Databricks Schema name (if applicable).
   * - ``model_retention_days``
     - ``90``
     - Days to keep archived model versions before GC.
   * - ``metric_buffer_size``
     - ``100``
     - Metrics buffered in memory before flushing to disk.
   * - ``auto_flush_metrics``
     - ``true``
     - Automatically flush metric buffers at end of run.
   * - ``enable_circuit_breaker``
     - ``false``
     - Protect the system during backend outages.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/global_config.toml
         [mlops]
         backend_type = "local"
         storage_path = "./mlops_data"
         model_retention_days = 90
         metric_buffer_size = 200
         auto_flush_metrics = true

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/global_config.yaml
         mlops:
           backend_type: local
           storage_path: "./mlops_data"
           model_retention_days: 90
           metric_buffer_size: 200
           auto_flush_metrics: true

   .. tab-item:: JSON

      .. code-block:: json

         {
           "mlops": {
             "backend_type": "local",
             "storage_path": "./mlops_data",
             "model_retention_days": 90,
             "metric_buffer_size": 200,
             "auto_flush_metrics": true
           }
         }

Tracking Inside a Node
----------------------

For an ``ml``-type pipeline, Ducta creates the experiment and run for you and
delivers everything a node needs through a typed ``ml_context`` argument (an
``MLNodeContext``). You just read the tracking handles from it and
log — no ``init``/``get_context`` calls:

.. code-block:: python

   from typing import Any, Optional
   from ducta import MLNodeContext   # typed, but ml_context also works as a dict


   def train(training_data: Any, ml_context: Optional[MLNodeContext] = None) -> Any:
       ml_context = ml_context or {}

       # Reproducibility + hyperparameters are supplied by Ducta
       seed = ml_context.get("node_seed", 42)
       params = {"n_estimators": 100, **(ml_context.get("hyperparams") or {})}

       model = my_trainer.fit(training_data, random_state=seed, **params)
       f1 = my_evaluator.score(model)

       # Log to the auto-created run, if MLOps is active for this pipeline
       mlops = ml_context.get("mlops_context")
       run_id = ml_context.get("mlops_run_id")
       if mlops and run_id and getattr(mlops, "experiment_tracker", None):
           tracker = mlops.experiment_tracker
           for key, value in params.items():
               tracker.log_parameter(run_id, key, value)
           tracker.log_metric(run_id, "f1", f1)

       return model

.. note::
   The run is opened before your node runs and closed after it returns
   (``COMPLETED`` on success, ``FAILED`` on exception) — you never manage its
   lifecycle. The ``ml_ready`` template
   (``ducta template --template ml_ready``) generates a complete, runnable
   version of this node.

Model Registry
--------------

The Ducta registry provides version-controlled model management. Newly registered models start in the **Staging** stage by default.

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - Stage
     - Description
   * - ``Staging``
     - Default stage. Used for validation and testing.
   * - ``Production``
     - Active model serving live predictions.
   * - ``Archived``
     - Deprecated versions. Eligible for garbage collection.

**Promotion (CLI — the recommended path):**

.. code-block:: bash

   # ducta model promote <name> <version> <staging|production|archived>
   ducta model promote sales_predictor 1.2.0 production

   # Clean up old versions past the retention window
   ducta model gc --dry-run

Promotion to ``production`` is checked against your promotion policy; use
``--force`` to bypass it (the bypass is audit-logged). See :doc:`cli_usage` for
the full ``ducta model`` and ``ducta experiment`` command reference.

Lineage & Reproducibility
-------------------------

Ducta MLOps captures essential metadata automatically to ensure reproducibility:

- **Data Fingerprinting:** Generates content digests for input/output datasets.
  ``fingerprint_mode`` selects how much is covered: ``exact`` (default —
  order-independent digest over every row), ``sample`` (schema plus the first
  ``fingerprint_sample_rows`` rows) or ``schema`` (schema and row count only).
  Each fingerprint records the engine and algorithm that produced it, so
  fingerprints measured differently are reported as *not comparable* rather
  than as changed data.
- **Environment Snapshot:** Records Python version, OS, installed packages, and Git commit hash for every run.
- **Config Snapshots:** A full copy of the active configuration is attached as a JSON artifact to the run.

Reliability
-----------

The registry is safe to use from concurrent runs: writes to metadata and
artifacts are applied atomically, so a failure part-way through a promotion or
registration rolls back cleanly instead of leaving a half-written model. Backend
health (storage reachable, tracking server up) is checked when MLOps
initializes, and problems surface in the run logs.

Next Steps
----------

- :doc:`tutorials/mlops` - Build a complete end-to-end ML pipeline.
- :doc:`best_practices` - Standards for naming experiments and models.
