MLOps Tutorial: Experiment Tracking and Model Registry
======================================================

.. note::

   **Production Ready**: Ducta's MLOps module is optimized for high-throughput metric logging and robust model versioning, with built-in support for MLflow and Databricks Unity Catalog.

Ducta provides a production-grade MLOps stack that lets you complement batch pipelines with experiment tracking,
artifact management, monitoring, and optional MLflow integration.

.. grid:: 1 2 2 2
   :gutter: 3

   .. grid-item-card:: 🧪 Experiment Tracking

      Log parameters, metrics (with rolling buffers), and artifacts with zero boilerplate.

   .. grid-item-card:: 📦 Model Registry

      Version-controlled model storage with lifecycle stages (Staging, Production, Archived).

   .. grid-item-card:: 📊 MLflow Sync

      Automatic mirroring of runs and models to MLflow/Databricks with nested run support.

   .. grid-item-card:: 🛡️ Resilience

      Thread-safe logging, file locks for registry, and automatic retry logic for transient errors.

This tutorial walks through a complete workflow:

1. Configure the MLOps context and storage backend.
2. Define the pipeline and node that execute the training script.
3. Use ``ExperimentTracker`` and ``ModelRegistry`` to log metrics, artifacts, and register models.
4. Inspect runs, promote models, and monitor health checks.

Prerequisites
-------------

* **Ducta with MLOps extras**: ``pip install ducta[mlops]``
* **Optional MLflow**: ``pip install mlflow`` when you want to mirror runs in MLflow.
* **ML framework**: ``pip install scikit-learn`` for the sample training script.
* **Storage backend**: Local filesystem or Databricks reachable for artifacts.

Step 1: Configure Ducta's MLOps Layer
--------------------------------------

Ducta discovers configuration from the ``config/`` directory. Add an ``mlops`` block to your ``config/global_settings.toml``.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/global_settings.toml
         [mlops]
         backend_type = "local"
         storage_path = "./mlops_data"
         model_retention_days = 90
         metric_buffer_size = 200
         auto_flush_metrics = true
         auto_cleanup_stale = true

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/global_settings.yaml
         mlops:
           backend_type: local
           storage_path: ./mlops_data
           model_retention_days: 90
           metric_buffer_size: 200
           auto_flush_metrics: true
           auto_cleanup_stale: true

   .. tab-item:: JSON

      .. code-block:: json

         {
           "mlops": {
             "backend_type": "local",
             "storage_path": "./mlops_data",
             "model_retention_days": 90,
             "metric_buffer_size": 200,
             "auto_flush_metrics": true,
             "auto_cleanup_stale": true
           }
         }

.. tip::

   **For Databricks/Unity Catalog**, use environment variables for secure authentication:
   ``DUCTA_MLOPS_BACKEND=databricks``, ``DATABRICKS_CATALOG=prod_catalog``.

Step 2: Define the Training Pipeline
-------------------------------------

Create a pipeline that executes your training script.

**Define the pipeline** (``config/pipelines.toml``):

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/pipelines.toml — the key IS the pipeline name (flat, no wrapper)
         [ml_training]
         description = "Train and register customer churn prediction model"
         type = "ml"
         nodes = ["train_churn_model"]
         model_version = "1.0.0"

         [ml_training.hyperparams]
         n_estimators = 150
         max_depth = 12

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/pipelines.yaml
         ml_training:
           description: "Train and register customer churn prediction model"
           type: ml
           nodes:
             - train_churn_model
           model_version: "1.0.0"
           hyperparams:
             n_estimators: 150
             max_depth: 12

   .. tab-item:: JSON

      .. code-block:: json

         {
           "ml_training": {
             "description": "Train and register customer churn prediction model",
             "type": "ml",
             "nodes": ["train_churn_model"],
             "model_version": "1.0.0",
             "hyperparams": {
               "n_estimators": 150,
               "max_depth": 12
             }
           }
         }

**Define the node** (``config/nodes.toml``):

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/nodes.toml — the key IS the node name (flat, no wrapper)
         [train_churn_model]
         function = "pipelines.ml.train_and_register"
         description = "Train RandomForest model and register to registry"

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/nodes.yaml
         train_churn_model:
           function: "pipelines.ml.train_and_register"
           description: "Train RandomForest model and register to registry"

   .. tab-item:: JSON

      .. code-block:: json

         {
           "train_churn_model": {
             "function": "pipelines.ml.train_and_register",
             "description": "Train RandomForest model and register to registry"
           }
         }

.. important::

   Set ``random_seed`` in your ``global_settings`` so training runs are
   reproducible. Ducta seeds ``random``, ``numpy`` and ``torch`` globally and
   exposes a deterministic per-node seed as ``ml_context["node_seed"]``:

   .. code-block:: toml

      # config/global_settings.toml (settings live at the top level)
      random_seed = 42

Step 3: Create the Training Script
----------------------------------

Ducta passes an ``ml_context`` dict to any node that accepts it (explicitly or
via ``**kwargs``). It carries the versioned hyperparameters, a deterministic
per-node seed, the pipeline-level experiment run id, and the MLOps context
(experiment tracker + model registry).

.. code-block:: python

   import tempfile
   from pathlib import Path

   import joblib
   import pandas as pd
   from sklearn.dummy import DummyClassifier
   from sklearn.ensemble import RandomForestClassifier
   from sklearn.metrics import f1_score
   from sklearn.model_selection import train_test_split


   def train_and_register(training_data: pd.DataFrame, start_date=None, end_date=None, ml_context=None):
       ml_context = ml_context or {}

       # Hyperparameters come from versioned config (pipelines.toml / --hyperparams),
       # with safe defaults for local runs outside the pipeline.
       params = {"n_estimators": 150, "max_depth": 12, **(ml_context.get("hyperparams") or {})}
       seed = ml_context.get("node_seed", 42)

       X = training_data.drop("churn", axis=1)
       y = training_data["churn"]

       # Stratified + seeded split: reproducible, and preserves the class
       # balance of an imbalanced target like churn.
       X_train, X_test, y_train, y_test = train_test_split(
           X, y, test_size=0.2, stratify=y, random_state=seed
       )

       # Trivial baseline: the floor any model must beat to add value.
       baseline = DummyClassifier(strategy="most_frequent").fit(X_train, y_train)
       baseline_f1 = f1_score(y_test, baseline.predict(X_test))

       model = RandomForestClassifier(**params, random_state=seed).fit(X_train, y_train)
       f1 = f1_score(y_test, model.predict(X_test))

       # Log to the pipeline-level run Ducta already started.
       mlops = ml_context.get("mlops_context")
       run_id = ml_context.get("mlops_run_id")
       if mlops and run_id:
           tracker = mlops.experiment_tracker
           for key, value in {**params, "seed": seed, "split": "stratified_80_20"}.items():
               tracker.log_parameter(run_id, key, value)
           tracker.log_metric(run_id, "f1", f1)
           tracker.log_metric(run_id, "baseline_f1", baseline_f1)
           tracker.log_metric(run_id, "f1_lift", f1 - baseline_f1)

       # Register only if the model beats the trivial baseline by a margin —
       # an absolute threshold (e.g. accuracy > 0.85) is meaningless on
       # imbalanced data, where predicting the majority class can pass it.
       if mlops and f1 > baseline_f1 + 0.05:
           with tempfile.TemporaryDirectory() as tmp:
               artifact = Path(tmp) / "model.joblib"
               joblib.dump(model, artifact)
               mlops.model_registry.register_model(
                   name="churn-predictor",
                   artifact_path=str(artifact),
                   artifact_type="model",
                   framework="sklearn",
                   hyperparameters={**params, "seed": seed},
                   metrics={"f1": f1, "baseline_f1": baseline_f1},
                   experiment_run_id=run_id,
               )

       return {"f1": f1, "baseline_f1": baseline_f1}

.. important::

   **The four habits this example encodes** — keep them in your own nodes:

   1. **Reproducible split**: ``random_state`` from config-driven seed, never unseeded.
   2. **Stratified split** for imbalanced targets (``stratify=y``).
   3. **Hyperparameters from config** (``ml_context["hyperparams"]``), never hardcoded —
      so every run's parameters are versioned and logged automatically.
   4. **Baseline comparison**: metrics are only meaningful relative to a trivial
      baseline; gates are relative (``f1 > baseline_f1 + margin``), not absolute.

Step 4: Run the Pipeline via CLI
---------------------------------

Execute the training pipeline using the Ducta CLI:

.. code-block:: bash

   # Validate and Run
   ducta start --env dev --pipeline ml_training

   # Override hyperparameters for one run (merged over config values)
   ducta start --env dev --pipeline ml_training --hyperparams '{"max_depth": 8}'

Hyperparameter sweeps
~~~~~~~~~~~~~~~~~~~~~

To search hyperparameters instead of guessing them, declare a sweep spec —
list values are expanded into the cartesian product, scalars stay fixed:

.. code-block:: yaml

   # sweeps/rf_grid.yaml
   n_estimators: [100, 200, 400]
   max_depth: [5, 12]
   class_weight: balanced

.. code-block:: bash

   ducta start --env dev --pipeline ml_training --sweep sweeps/rf_grid.yaml

This runs one pipeline execution per combination (6 here), all tagged with a
shared ``sweep_id`` in the experiment tracker so you can group and compare
them: every candidate's parameters and metrics stay recorded, not just the
winner's.

Declarative train/test split
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Version the split criteria in the pipeline config instead of hardcoding them
in node code:

.. code-block:: toml

   # config/pipelines.toml — flat: [<pipeline_name>.split]
   [ml_training.split]
   method = "stratified"      # random | stratified | temporal | group
   test_size = 0.2
   stratify_col = "churn"

Nodes apply it with one call — the same config also gets logged to the run:

.. code-block:: python

   from ducta.mlrun import split_dataframe

   train_df, test_df = split_dataframe(
       data, ml_context["split"], default_seed=ml_context.get("node_seed")
   )

Use ``method = "group"`` with ``group_col`` when the same entity (customer,
device) appears in several rows, so it never lands on both sides of the split;
use ``method = "temporal"`` with ``time_col`` to cut without shuffling time.

Promotion gates
~~~~~~~~~~~~~~~

Block promotions to Production that do not beat the current model (or the
trivial baseline) by a margin:

.. code-block:: toml

   [mlops.promotion_policy]
   metric = "f1"
   min_delta = 0.01
   compare_to = "current_production"   # or "baseline"

.. code-block:: bash

   ducta model promote churn-predictor 3 production
   # blocked if v3 does not beat Production by min_delta on f1;
   # bypass consciously (audit-logged): --force

Reproducibility guards
~~~~~~~~~~~~~~~~~~~~~~

Two settings turn lineage recording into guarantees:

.. code-block:: toml

   # config/global_settings.toml (top-level settings)
   random_seed = 42            # seeds random/numpy/torch + per-node ml_context["node_seed"]
   fingerprint_policy = "warn" # record | warn | fail when inputs changed vs previous run

With ``fingerprint_policy = "fail"`` the pipeline aborts before training on
data that changed since the previous successful run of the same pipeline.

Step 5: Monitoring and Health
------------------------------

Ducta includes built-in monitoring for MLOps infrastructure health.

.. grid:: 1 2 2 2
   :gutter: 3

   .. grid-item-card:: 🔍 Health Checks

      Verify storage availability, disk space, and backend connectivity.

      .. code-block:: python

         from ducta.mlrun import HealthMonitor
         monitor = HealthMonitor()
         report = monitor.check_health()
         print(f"Status: {report.overall_status}")

   .. grid-item-card:: 📈 Operational Metrics

      Track system-level metrics like registration counts and active runs.

      .. code-block:: python

         from ducta.mlrun import get_metrics_collector
         collector = get_metrics_collector()
         print(f"Active Runs: {collector.get_counter('active_runs')}")

Next Steps
----------

* :doc:`/getting_started` - Application of the configuration flow.
* :doc:`/tutorials/streaming` - Keeping training data fresh with streaming ETLs.
