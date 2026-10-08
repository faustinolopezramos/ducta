Getting Started
===============

Welcome to Ducta! In this guide, you will build and execute your first professional data pipeline in just a few minutes.

Ducta follows a **Configuration-As-Code** philosophy: you define *what* your pipeline does in a few YAML files, and *how* it does it in clean Python functions.

Step 1: Initialize Your Project
-------------------------------

Ducta provides production-ready templates to get you started immediately. Run the following commands to create your first project:

.. code-block:: bash

   # Generate a project based on the Medallion Architecture pattern
   ducta template --template medallion_basic --project-name my_pipeline

   # ...or, with the layout a larger project grows into (catalog/ by layer, quality/profiles)
   ducta init project --name my_pipeline

   # Enter the project directory
   cd my_pipeline

.. note::
   The ``medallion_basic`` template sets up a best-practice structure with Bronze, Silver, and Gold layers.

Step 2: Explore the Project Structure
-------------------------------------

Ducta separates *what* runs from *how*:

.. grid:: 1 1 2 2
   :gutter: 2

   .. grid-item::
      **📄 ducta.yaml · catalog.yaml · pipelines/*.yaml**

      What runs: settings and environments, every dataset once, and each pipeline with its nodes.

   .. grid-item::
      **🐍 pipelines/*.py**

      How: plain Python functions. No infrastructure code needed.

.. code-block:: text

   my_pipeline/
   ├── ducta.yaml             # project, paths, settings, per-environment overrides
   ├── catalog.yaml           # every dataset: format, location, how it is written, its checks
   ├── pipelines/
   │   ├── etl.yaml           # the `etl` pipeline and its nodes
   │   └── etl.py             # your Python logic (extract/transform/load)
   ├── .ducta/schema/         # JSON Schemas — autocompletion in your editor
   └── .env                   # secrets & machine-local values

Step 3: Execute Your First Pipeline
-----------------------------------

The template comes with an ``etl`` pipeline ready to run. Let's execute it:

.. code-block:: bash

   ducta start --env dev --pipeline etl

**What just happened?**

1. **Validation**: every file was checked against the schema, and every dataset a
   node names against the catalog — a typo is reported with its file and line.
2. **Dependency Resolution**: the order came from the data — ``transform`` reads what
   ``extract`` writes.
3. **Environment Loading**: ``environments.dev`` in ``ducta.yaml`` (if any) was applied,
   and variables were read from ``.env``.
4. **Execution**: your functions ran, with the quality checks and gates in between.
5. **Evidence**: a run certificate recorded what ran, on which data, with which result
   (``ducta certify list``).

Step 4: Customizing the Pipeline
--------------------------------

Open ``pipelines/etl.yaml``:

.. code-block:: yaml

   # pipelines/etl.yaml — the file name is the pipeline name
   description: "Complete ETL pipeline: Extract -> Transform -> Load"
   requires_dates: false
   nodes:
     extract:
       run: pipelines.etl:extract
       inputs: [source_data]
       outputs: [bronze.etl.raw_data]
     transform:
       run: pipelines.etl:transform
       inputs: [bronze.etl.raw_data]
       outputs: [silver.etl.clean_data]
       quality:
         checks:
           null_rate: {columns: [amount], threshold: 0.0}
         gate: {max_errors: 0}
     load:
       run: pipelines.etl:load
       inputs: [silver.etl.clean_data]
       outputs: [gold.etl.final_output]

To add a step, add a node here and the datasets it writes to ``catalog.yaml``.
``ducta config validate`` checks the result without running anything.

When a value is not what you expected, follow it instead of searching the files:

.. code-block:: bash

   ducta config validate                       # every problem, with file and line
   ducta config show --env prod                # the project as prod resolves it
   ducta config explain settings.max_parallel_nodes --env prod   # which file and line set it
   ducta config diff dev prod                  # every value that differs between two environments

.. tip::
   Five starter templates exist — ``ducta template --list-templates`` shows them:
   ``medallion_basic`` (batch ETL, bronze → silver → gold), ``streaming_basic``
   (Structured Streaming), ``ml_basic`` (a churn model with a declarative split
   and a baseline gate), ``ml_scoring`` (train and promote a model, then score
   new data with it) and ``hybrid_basic`` (a batch node feeding a stream, in
   one pipeline). Each one runs as generated.

Step 5: Pure Python Logic
-------------------------

Take a look at ``pipelines/etl.py``. Notice there are **no Ducta-specific imports or decorators**
— Ducta loads the configured input dataset and passes it to your function as a positional argument:

.. code-block:: python

   from typing import Any
   from loguru import logger


   def extract(source_data: Any) -> Any:
       """A simple, testable Python function."""
       logger.info("Extracting data from source")
       if source_data is None:
           raise ValueError("No data provided from source")
       return source_data

This makes your code highly portable and easy to unit test.

Next Steps
----------

Now that you've mastered the basics, dive deeper:

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: ⚙️ Master Configuration
      :link: configuration
      :link-type: doc

      Learn how to use environment variables, conditional steps, and reusable nodes.

   .. grid-item-card:: 💻 CLI Mastery
      :link: cli_usage
      :link-type: doc

      Discover powerful flags for debugging, partial runs, and validation.

   .. grid-item-card:: ☁️ Cloud Deployment
      :link: databricks_setup
      :link-type: doc

      Learn how to take your local pipeline to Databricks or Spark clusters.

   .. grid-item-card:: 🧪 Best Practices
      :link: best_practices
      :link-type: doc

      Learn the "Ducta Way" to structure large-scale data projects.
