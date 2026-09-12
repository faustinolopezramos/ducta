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

Ducta discovers configuration from the ``config/`` directory. Add an ``mlops`` block to your ``config/global_config.toml``.

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
         auto_cleanup_stale = true

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/global_config.yaml
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

         # Declared once here, applied by the node via split_dataframe — the
         # run certificate then records the split that actually ran.
         [ml_training.split]
         method = "stratified"
         stratify_col = "churn"
         test_size = 0.2
         val_size = 0.1

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
           # Declared once here, applied by the node via split_dataframe — the
           # run certificate then records the split that actually ran.
           split:
             method: stratified
             stratify_col: churn
             test_size: 0.2
             val_size: 0.1

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
             },
             "split": {
               "method": "stratified",
               "stratify_col": "churn",
               "test_size": 0.2,
               "val_size": 0.1
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

   Set ``random_seed`` in your ``global_config`` so training runs are
   reproducible. Ducta seeds ``random``, ``numpy`` and ``torch`` globally and
   exposes a deterministic per-node seed as ``ml_context["node_seed"]``:

   .. code-block:: toml

      # config/global_config.toml (settings live at the top level)
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

   from ducta.mlrun import split_dataframe


   def train_and_register(training_data: pd.DataFrame, start_date=None, end_date=None, ml_context=None):
       ml_context = ml_context or {}

       # Hyperparameters come from versioned config (pipelines.toml / --hyperparams),
       # with safe defaults for local runs outside the pipeline.
       params = {"n_estimators": 150, "max_depth": 12, **(ml_context.get("hyperparams") or {})}
       seed = ml_context.get("node_seed", 42)

       # The split is declared once in pipelines.toml ([ml_training.split]) and
       # applied here — passing ml_context marks split_applied on it, so the
       # engine can confirm the split it logged to the run is the split that
       # actually ran. Model selection happens on val; test is touched exactly
       # once, at the end, purely to report an unbiased estimate.
       train, val, test = split_dataframe(
           training_data, ml_context.get("split"), default_seed=seed, ml_context=ml_context,
       )
       X_train, y_train = train.drop("churn", axis=1), train["churn"]
       X_val, y_val = val.drop("churn", axis=1), val["churn"]
       X_test, y_test = test.drop("churn", axis=1), test["churn"]

       # Trivial baseline: the floor any model must beat to add value.
       baseline = DummyClassifier(strategy="most_frequent").fit(X_train, y_train)
       baseline_f1 = f1_score(y_val, baseline.predict(X_val))

       model = RandomForestClassifier(**params, random_state=seed).fit(X_train, y_train)
       val_f1 = f1_score(y_val, model.predict(X_val))

       # Test is scored once, after the model is already chosen on val — never
       # used to pick hyperparameters or to decide whether to register.
       test_f1 = f1_score(y_test, model.predict(X_test))

       # Log to the pipeline-level run Ducta already started.
       mlops = ml_context.get("mlops_context")
       run_id = ml_context.get("mlops_run_id")
       if mlops and run_id:
           tracker = mlops.experiment_tracker
           for key, value in {**params, "seed": seed}.items():
               tracker.log_parameter(run_id, key, value)
           tracker.log_metric(run_id, "val_f1", val_f1)
           tracker.log_metric(run_id, "baseline_f1", baseline_f1)
           tracker.log_metric(run_id, "val_f1_lift", val_f1 - baseline_f1)
           tracker.log_metric(run_id, "test_f1", test_f1)

       # Register only if the model beats the trivial baseline on val by a
       # margin — an absolute threshold (e.g. accuracy > 0.85) is meaningless on
       # imbalanced data, where predicting the majority class can pass it.
       if mlops and val_f1 > baseline_f1 + 0.05:
           with tempfile.TemporaryDirectory() as tmp:
               artifact = Path(tmp) / "model.joblib"
               joblib.dump(model, artifact)
               mlops.model_registry.register_model(
                   name="churn-predictor",
                   artifact_path=str(artifact),
                   artifact_type="model",
                   framework="sklearn",
                   hyperparameters={**params, "seed": seed},
                   metrics={"val_f1": val_f1, "baseline_f1": baseline_f1, "test_f1": test_f1},
                   experiment_run_id=run_id,
               )

       return {"val_f1": val_f1, "baseline_f1": baseline_f1, "test_f1": test_f1}

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

The ``[ml_training.split]`` block from Step 3 versions the split criteria in
the pipeline config instead of hardcoding them in node code, and
``train_and_register`` already applies it with one call — passing
``ml_context=`` marks ``ml_context["split_applied"]``, so the run certificate
is guaranteed to record the split that actually ran, not just the split that
was configured:

.. code-block:: python

   from ducta.mlrun import split_dataframe

   train, val, test = split_dataframe(
       data, ml_context["split"], default_seed=ml_context.get("node_seed"),
       ml_context=ml_context,
   )

``val_size`` is what makes this a 3-way split: model selection happens on
``val``, and ``test`` is scored exactly once, at the end, to report an
unbiased estimate — never used to choose hyperparameters or to decide
whether to register. Omit ``val_size`` for a plain 2-way ``(train, test)``
split. Use ``method = "group"`` with ``group_col`` when the same entity
(customer, device) appears in several rows, so it never lands on both sides
of the split; use ``method = "temporal"`` with ``time_col`` to cut without
shuffling time.

.. warning::

   If a node declares a ``split`` but never calls ``split_dataframe``/
   ``kfold_splits``, Ducta logs a warning — the certificate would otherwise
   record a split configuration that the node silently ignored.

Promotion gates
~~~~~~~~~~~~~~~

Block promotions to Production that do not beat the current model (or the
trivial baseline) by a margin:

.. code-block:: toml

   [mlops.promotion_policy]
   metric = "val_f1"
   min_delta = 0.01
   compare_to = "current_production"   # or "baseline"

.. code-block:: bash

   ducta model promote churn-predictor 3 production
   # blocked if v3 does not beat Production by min_delta on val_f1;
   # bypass consciously (audit-logged): --force

Reproducibility guards
~~~~~~~~~~~~~~~~~~~~~~

Two settings turn lineage recording into guarantees:

.. code-block:: toml

   # config/global_config.toml (top-level settings)
   random_seed = 42            # seeds random/numpy/torch + per-node ml_context["node_seed"]
   fingerprint_policy = "warn" # record | warn | fail when inputs changed vs previous run

With ``fingerprint_policy = "fail"`` the pipeline aborts before training on
data that changed since the previous successful run of the same pipeline.

Next Steps
----------

* :doc:`/getting_started` - Application of the configuration flow.
* :doc:`/tutorials/streaming` - Keeping training data fresh with streaming ETLs.
