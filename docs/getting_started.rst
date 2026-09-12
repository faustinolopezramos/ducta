Getting Started
===============

Welcome to Ducta! In this guide, you will build and execute your first professional data pipeline in just a few minutes.

Ducta follows a **Configuration-As-Code** philosophy: you define *what* your pipeline does in simple TOML/YAML files, and *how* it does it in clean Python functions.

Step 1: Initialize Your Project
-------------------------------

Ducta provides production-ready templates to get you started immediately. Run the following commands to create your first project:

.. code-block:: bash

   # Generate a project based on the Medallion Architecture pattern
   ducta template --template medallion_basic --project-name my_pipeline

   # Enter the project directory
   cd my_pipeline

.. note::
   The ``medallion_basic`` template sets up a best-practice structure with Bronze, Silver, and Gold layers.

Step 2: Explore the Project Structure
-------------------------------------

Ducta enforces a clean separation of concerns:

.. grid:: 1 1 2 2
   :gutter: 2

   .. grid-item::
      **📁 config/**

      The "Brain" of your project. Define your pipeline logic, data sources, and environment settings here.

   .. grid-item::
      **📁 pipelines/**

      The "Muscle". This is where your pure Python logic lives. No infrastructure code needed.

.. code-block:: text

   my_pipeline/
   ├── environment.yaml          # Maps each environment to its config files
   ├── config/
   │   ├── global_config.yaml  # Project-wide settings
   │   ├── pipelines.yaml        # Workflows: which nodes run, in what order
   │   ├── nodes.yaml            # Step definitions
   │   ├── input.yaml            # Input sources catalog
   │   ├── output.yaml           # Output destinations catalog
   │   ├── dev/                  # Per-environment overrides
   │   ├── sandbox/              # (global_config / input / output only)
   │   └── prod/
   ├── pipelines/
   │   └── etl.py                # Your Python logic (extract/transform/load)
   └── .env                      # Secrets & machine-local values

Step 3: Execute Your First Pipeline
-----------------------------------

The template comes with an ``etl`` pipeline ready to run. Let's execute it:

.. code-block:: bash

   ducta start --env base --pipeline etl

**What just happened?**
When you ran that command, Ducta performed several enterprise-grade actions:

1. **Validation**: Verified that all nodes defined in ``pipelines.yaml`` exist in ``nodes.yaml``.
2. **Dependency Resolution**: Calculated the correct order of execution.
3. **Environment Loading**: Automatically picked up variables from your ``.env`` file.
4. **Execution**: Ran your Python functions and managed the data flow between them.
5. **Observability**: Generated detailed logs (check the console output!) and execution metrics.

Step 4: Customizing the Pipeline
--------------------------------

Open ``config/pipelines.yaml`` (or the TOML/JSON equivalent). You'll see how simple it is to define a workflow:

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/pipelines.toml — the top-level key IS the pipeline name (flat, no wrapper)
         [etl]
         description = "Complete ETL pipeline: Extract -> Transform -> Load"
         type = "batch"
         nodes = ["extract", "transform", "load"]
         inputs = ["source_data"]
         outputs = ["gold.etl.final_output"]

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/pipelines.yaml — the top-level key IS the pipeline name (flat, no wrapper)
         etl:
           description: "Complete ETL pipeline: Extract -> Transform -> Load"
           type: batch
           nodes:
             - extract
             - transform
             - load
           inputs:
             - source_data
           outputs:
             - gold.etl.final_output

   .. tab-item:: JSON

      .. code-block:: json

         {
           "etl": {
             "description": "Complete ETL pipeline: Extract -> Transform -> Load",
             "type": "batch",
             "nodes": ["extract", "transform", "load"],
             "inputs": ["source_data"],
             "outputs": ["gold.etl.final_output"]
           }
         }

To add a new step, add its name to the ``nodes`` list and define it in
``config/nodes.yaml``.

.. tip::
   ``medallion_basic`` is one of four starter templates. Run
   ``ducta template --list-templates`` to see them all: ``medallion_basic``
   (batch ETL), ``ml_ready`` (adds experiment tracking + model registry),
   ``streaming_core`` (real-time), and ``hybrid`` (batch feeding streaming).

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
