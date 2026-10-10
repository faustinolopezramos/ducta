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

Tracking is on by itself for ``type: ml`` pipelines. What you decide in
``ducta.yaml`` is where it is kept, whether a run may go without it, and the seed
that makes training reproducible:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "churn"

         [paths]
         input = "data"
         output = "data"

         [settings]
         random_seed = 42
         mlops_path = "models"
         mlops_required = false

         [environments.dev.settings]
         mlops_enabled = false

         [environments.prod.settings]
         mlops_required = true

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: churn
         paths: {input: data, output: data}
         settings:
           random_seed: 42              # seeds random/numpy/torch + ml_context["node_seed"]
           mlops_path: models           # experiments and model registry live here
           mlops_required: false
         environments:
           dev:
             settings: {mlops_enabled: false}      # no tracking while iterating
           prod:
             settings: {mlops_required: true}      # no tracking, no run

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "churn",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "settings": {
             "random_seed": 42,
             "mlops_path": "models",
             "mlops_required": false
           },
           "environments": {
             "dev": {
               "settings": {
                 "mlops_enabled": false
               }
             },
             "prod": {
               "settings": {
                 "mlops_required": true
               }
             }
           }
         }

Retention, buffering and backend options are environment variables
(``Ducta_MLOPS_*``); the table is in :doc:`../mlops`.

Ducta seeds ``random``, ``numpy`` and ``torch`` globally from ``random_seed``
and gives each node a deterministic seed of its own.

Step 2: Define the Training Pipeline
-------------------------------------

The training data is a dataset like any other:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # catalog.toml
         ["gold.churn.training_set"]
         format = "parquet"
         use_pandas = true

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # catalog.yaml
         gold.churn.training_set:
           format: parquet
           use_pandas: true                 # the node receives a pandas DataFrame

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "gold.churn.training_set": {
             "format": "parquet",
             "use_pandas": true
           }
         }

The pipeline is ``type: ml``; its hyperparameters and split are versioned here,
not in code:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/ml_training.toml
         description = "Train and register the customer churn model"
         type = "ml"
         requires_dates = false
         model_version = "1.0.0"

         [hyperparams]
         n_estimators = 150
         max_depth = 12

         [split]
         method = "stratified"
         stratify_col = "churn"
         test_size = 0.2
         val_size = 0.1

         [nodes.train_churn_model]
         description = "Train a RandomForest and register it when it beats the baseline"
         run = "pipelines.ml:train_and_register"

         [nodes.train_churn_model.inputs]
         training_data = "gold.churn.training_set"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/ml_training.yaml
         description: Train and register the customer churn model
         type: ml
         requires_dates: false
         model_version: "1.0.0"
         hyperparams: {n_estimators: 150, max_depth: 12}
         split:                              # applied by the node via split_dataframe
           method: stratified
           stratify_col: churn
           test_size: 0.2
           val_size: 0.1
         nodes:
           train_churn_model:
             description: Train a RandomForest and register it when it beats the baseline
             run: pipelines.ml:train_and_register
             inputs: {training_data: gold.churn.training_set}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "description": "Train and register the customer churn model",
           "type": "ml",
           "requires_dates": false,
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
           },
           "nodes": {
             "train_churn_model": {
               "description": "Train a RandomForest and register it when it beats the baseline",
               "run": "pipelines.ml:train_and_register",
               "inputs": {
                 "training_data": "gold.churn.training_set"
               }
             }
           }
         }

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


   def train_and_register(training_data: pd.DataFrame, ml_context=None):
       ml_context = ml_context or {}

       # Hyperparameters come from versioned config (pipelines/ml_training.yaml or
       # --hyperparams),
       # with safe defaults for local runs outside the pipeline.
       params = {"n_estimators": 150, "max_depth": 12, **(ml_context.get("hyperparams") or {})}
       seed = ml_context.get("node_seed", 42)

       # The split is declared once in pipelines/ml_training.yaml (split:) and
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

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # sweeps/rf_grid.toml
         n_estimators = [
             100,
             200,
             400,
         ]
         max_depth = [
             5,
             12,
         ]
         class_weight = "balanced"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # sweeps/rf_grid.yaml
         n_estimators: [100, 200, 400]
         max_depth: [5, 12]
         class_weight: balanced

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "n_estimators": [
             100,
             200,
             400
           ],
           "max_depth": [
             5,
             12
           ],
           "class_weight": "balanced"
         }

.. code-block:: bash

   ducta start --env dev --pipeline ml_training --sweep sweeps/rf_grid.yaml

This runs one pipeline execution per combination (6 here), all tagged with a
shared ``sweep_id`` in the experiment tracker so you can group and compare
them: every candidate's parameters and metrics stay recorded, not just the
winner's.

Declarative train/test split
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``split`` block from Step 2 versions the split criteria in
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
split. Use ``method: group`` with ``group_col`` when the same entity
(customer, device) appears in several rows, so it never lands on both sides
of the split; use ``method: temporal`` with ``time_col`` to cut without
shuffling time.

.. warning::

   If a node declares a ``split`` but never calls ``split_dataframe``/
   ``kfold_splits``, Ducta logs a warning — the certificate would otherwise
   record a split configuration that the node silently ignored.

Promotion gates
~~~~~~~~~~~~~~~

Block promotions to Production that do not beat the current model (or the
trivial baseline) by a margin:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "churn"

         [paths]
         input = "data"
         output = "data"

         [settings.mlops.promotion_policy]
         metric = "val_f1"
         min_delta = 0.01
         compare_to = "current_production"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: churn
         paths: {input: data, output: data}
         settings:
           mlops:
             promotion_policy:
               metric: val_f1
               min_delta: 0.01
               compare_to: current_production   # or baseline

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "churn",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "settings": {
             "mlops": {
               "promotion_policy": {
                 "metric": "val_f1",
                 "min_delta": 0.01,
                 "compare_to": "current_production"
               }
             }
           }
         }

.. code-block:: bash

   ducta model promote churn-predictor 3 production
   # blocked if v3 does not beat Production by min_delta on val_f1;
   # bypass consciously (audit-logged): --force

Reproducibility guards
~~~~~~~~~~~~~~~~~~~~~~

Two settings turn lineage recording into guarantees:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "churn"

         [paths]
         input = "data"
         output = "data"

         [settings]
         random_seed = 42
         fingerprint_policy = "warn"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: churn
         paths: {input: data, output: data}
         settings:
           random_seed: 42              # seeds random/numpy/torch + per-node ml_context["node_seed"]
           fingerprint_policy: warn     # record | warn | fail when inputs changed vs previous run

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "churn",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "settings": {
             "random_seed": 42,
             "fingerprint_policy": "warn"
           }
         }

With ``fingerprint_policy: fail`` the pipeline aborts before training on
data that changed since the previous successful run of the same pipeline.

Next Steps
----------

* :doc:`/getting_started` - Application of the configuration flow.
* :doc:`/tutorials/streaming` - Keeping training data fresh with streaming ETLs.
