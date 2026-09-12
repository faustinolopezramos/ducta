Configuration Formats: TOML, YAML, and JSON
===========================================

Ducta is designed to be flexible. You can define your pipelines and configurations in the format that best suits your team: **TOML** (recommended), **YAML**, or **JSON**.

This tutorial provides functional, side-by-side examples of the core configuration files.

Basic Project Structure
-----------------------

Regardless of the format you choose, your configuration files should live in the ``config/`` directory:

.. code-block:: text

   my_project/
   ├── environment.toml               # maps environments to config files
   ├── config/
   │   ├── global_config.toml (or .yaml/.json)
   │   ├── pipelines.toml
   │   ├── nodes.toml
   │   ├── input.toml
   │   └── output.toml
   └── src/
       └── processing.py

.. note::
   Every config file is **flat**: the top-level keys are the pipeline names
   (in ``pipelines``), node names (in ``nodes``), or dataset names (in
   ``input``/``output``). There is no ``pipelines:`` / ``nodes:`` / ``inputs:``
   wrapper key.

1. Pipeline Definition
----------------------

The pipeline file defines the "workflow"—the order in which nodes (steps) are executed.

.. tab-set::

   .. tab-item:: TOML (Recommended)

      .. code-block:: toml

         # config/pipelines.toml — the key IS the pipeline name
         [hello_world]
         description = "A simple greeting pipeline"
         type = "batch"
         nodes = ["say_hello", "say_goodbye"]

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/pipelines.yaml
         hello_world:
           description: "A simple greeting pipeline"
           type: batch
           nodes:
             - say_hello
             - say_goodbye

   .. tab-item:: JSON

      .. code-block:: json

         {
           "hello_world": {
             "description": "A simple greeting pipeline",
             "type": "batch",
             "nodes": ["say_hello", "say_goodbye"]
           }
         }

2. Node Definition
------------------

Nodes map a step name to a specific Python function and define its execution parameters.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/nodes.toml — the key IS the node name
         [say_hello]
         function = "src.processing.hello"
         timeout = 300
         retry = 3

         [say_goodbye]
         function = "src.processing.goodbye"

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/nodes.yaml
         say_hello:
           function: "src.processing.hello"
           timeout: 300
           retry: 3
         say_goodbye:
           function: "src.processing.goodbye"

   .. tab-item:: JSON

      .. code-block:: json

         {
           "say_hello": {
             "function": "src.processing.hello",
             "timeout": 300,
             "retry": 3
           },
           "say_goodbye": {
             "function": "src.processing.goodbye"
           }
         }

3. Data Catalog (I/O)
---------------------

Inputs and outputs live in **two separate flat files** — the top-level key is
the dataset name that nodes reference in their ``input``/``output`` lists.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/input.toml
         [users]
         format = "csv"
         filepath = "data/users.csv"

      .. code-block:: toml

         # config/output.toml
         [report]
         format = "parquet"
         filepath = "data/report.parquet"

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/input.yaml
         users:
           format: "csv"
           filepath: "data/users.csv"

      .. code-block:: yaml

         # config/output.yaml
         report:
           format: "parquet"
           filepath: "data/report.parquet"

   .. tab-item:: JSON

      .. code-block:: json

         // config/input.json
         {
           "users": {
             "format": "csv",
             "filepath": "data/users.csv"
           }
         }

         // config/output.json
         {
           "report": {
             "format": "parquet",
             "filepath": "data/report.parquet"
           }
         }

Mixing Formats
--------------

Ducta allows you to mix formats. For example, you could have ``pipelines.toml`` and ``nodes.yaml`` in the same project. However, for consistency and ease of maintenance, we recommend sticking to one format (ideally **TOML**).

Running Your Pipeline
---------------------

No matter which format you use, the command to run remains the same:

.. code-block:: bash

   ducta start --pipeline hello_world

Ducta resolves configuration relative to the current working directory (or
``--base-path``, if given): it looks for a settings file
(``environment.yml``, ``settings.yaml``, ``settings.json``, or
``config.json``) up to three directory levels deep, and that file's
``env_config`` section points to the actual pipeline, node, and data/I-O
config files for each environment — it does not glob every ``.toml``/``.yaml``/``.json``
file under ``config/`` automatically.
