Databricks Integration Guide
=============================

This guide explains how to use Ducta with Databricks infrastructure for large-scale pipeline execution.

**Important**: Ducta executes pipelines on your infrastructure. Databricks setup and infrastructure provisioning is your responsibility.

Prerequisites
-------------

You need:
- A Databricks workspace configured and running
- Databricks access token or service principal credentials
- Appropriate permissions in Databricks to read/write data
- Unity Catalog enabled (recommended for production)

Setting Up Ducta for Databricks
---------------------------------

**Step 1: Configure credentials**

Ducta delegates Databricks authentication to ``databricks-connect`` and the Databricks SDK's own ``Config`` auto-resolution — it does **not** read host/token/cluster settings from Ducta's own TOML/YAML/JSON configuration. Set the standard Databricks environment variables instead:

.. code-block:: bash

   export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
   export DATABRICKS_TOKEN=dapi1234567890abcdefg
   export DATABRICKS_CLUSTER_ID=cluster-123456

Or add to your ``.env`` file:

.. code-block:: bash

   DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
   DATABRICKS_TOKEN=your_token_here
   DATABRICKS_CLUSTER_ID=cluster-123456

The Databricks SDK also supports resolving these from a named profile in ``~/.databrickscfg`` (set ``DATABRICKS_CONFIG_PROFILE`` instead of the variables above). ``host``, ``token``, and ``cluster_id`` are required; Ducta raises a configuration error at session creation if any of them is missing.

**Step 2: Configure Ducta's execution mode**

Set ``mode`` to ``"databricks"`` and point ``input_path``/``output_path`` at your data locations (Unity Catalog Volumes paths work well here) in your global configuration. These are Ducta's own settings — they are independent of the Databricks credentials above, which come exclusively from the environment.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         mode = "databricks"

         # Use Unity Catalog Volumes paths
         input_path = "/Volumes/catalog/schema/input"
         output_path = "/Volumes/catalog/schema/output"

   .. tab-item:: YAML

      .. code-block:: yaml

         mode: databricks

         input_path: /Volumes/catalog/schema/input
         output_path: /Volumes/catalog/schema/output

   .. tab-item:: JSON

      .. code-block:: json

         {
           "mode": "databricks",
           "input_path": "/Volumes/catalog/schema/input",
           "output_path": "/Volumes/catalog/schema/output"
         }

**Step 3: Run your pipeline**

.. code-block:: bash

   ducta start --env prod --pipeline my_pipeline

Ducta will execute the pipeline on your Databricks cluster.

Common Patterns
---------------

**Using Delta Lake tables as input/output**

Ducta's Delta reader/writer always resolve the dataset's ``filepath`` through Spark's path-based ``.load()``/``.save()`` API (not ``spark.read.table()``), so ``filepath`` must be a filesystem-style location — a Unity Catalog Volumes path, ``dbfs:/`` path, or cloud URI — rather than a ``catalog.schema.table`` identifier.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/input.toml — flat: the key IS the dataset name
         [customer_data]
         filepath = "/Volumes/delta_catalog/main/customers"
         format = "delta"

      .. code-block:: toml

         # config/output.toml
         [processed]
         filepath = "/Volumes/delta_catalog/main/customers_processed"
         format = "delta"

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/input.yaml
         customer_data:
           filepath: /Volumes/delta_catalog/main/customers
           format: delta

      .. code-block:: yaml

         # config/output.yaml
         processed:
           filepath: /Volumes/delta_catalog/main/customers_processed
           format: delta

   .. tab-item:: JSON

      .. code-block:: json

         {
           "customer_data": {
             "filepath": "/Volumes/delta_catalog/main/customers",
             "format": "delta"
           }
         }

**Running on a specific cluster**

Ducta's Databricks Connect session always targets a cluster, identified by ``DATABRICKS_CLUSTER_ID`` (or the equivalent value in your ``~/.databrickscfg`` profile). There is no separate SQL warehouse execution mode — set the environment variable before starting the pipeline:

.. code-block:: bash

   export DATABRICKS_CLUSTER_ID=cluster-abc123
   ducta start --env prod --pipeline my_pipeline

Troubleshooting
---------------

**"Authentication failed"**

- Verify your token is valid
- Check DATABRICKS_HOST format
- Ensure token has appropriate permissions

**"Cluster not found"**

- Verify cluster_id is correct
- Ensure cluster is running

**"Path not found in Unity Catalog"**

- Use a full Volumes path: ``/Volumes/<catalog>/<schema>/<volume>/...``
- Verify you have read/write permissions

Next Steps
----------

- :doc:`configuration` - Configure other data sources
- :doc:`best_practices` - Learn production best practices
- :doc:`tutorials/batch_etl` - See a real example
