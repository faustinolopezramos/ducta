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

Set ``mode: databricks`` and point ``paths`` at your data — Unity Catalog
Volumes paths work well. Usually only production runs on Databricks, so put it
in that environment's overrides and keep local development local:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "sales"

         [paths]
         input = "data"
         output = "data"

         [settings]
         mode = "local"

         [environments.prod.settings]
         mode = "databricks"

         [environments.prod.paths]
         input = "/Volumes/main/sales/input"
         output = "/Volumes/main/sales/output"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: sales
         paths: {input: data, output: data}
         settings: {mode: local}
         environments:
           prod:
             settings: {mode: databricks}
             paths:
               input: /Volumes/main/sales/input
               output: /Volumes/main/sales/output

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "sales",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "settings": {
             "mode": "local"
           },
           "environments": {
             "prod": {
               "settings": {
                 "mode": "databricks"
               },
               "paths": {
                 "input": "/Volumes/main/sales/input",
                 "output": "/Volumes/main/sales/output"
               }
             }
           }
         }

These are Ducta's own settings, independent of the Databricks credentials
above, which come only from the environment.

**Step 3: Run your pipeline**

.. code-block:: bash

   ducta start --env prod --pipeline my_pipeline

Ducta will execute the pipeline on your Databricks cluster.

Common Patterns
---------------

**Delta Lake tables as inputs and outputs**

Ducta reads and writes Delta through paths (``.load()``/``.save()``), so a
dataset's ``path`` is a filesystem-style location — a Volumes path, a
``dbfs:/`` path or a cloud URI — not a ``catalog.schema.table`` identifier:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # catalog.toml
         [customers]
         format = "delta"
         path = "/Volumes/main/crm/customers"

         ["silver.crm.customers_clean"]
         format = "delta"

         ["silver.crm.customers_clean".write]
         mode = "merge"

         ["silver.crm.customers_clean".write.merge]
         keys = [
             "customer_id",
         ]

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # catalog.yaml
         customers:
           format: delta
           path: /Volumes/main/crm/customers
         silver.crm.customers_clean:              # no path: <paths.output>/<env>/silver/crm/customers_clean
           format: delta
           write:
             mode: merge
             merge: {keys: [customer_id]}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "customers": {
             "format": "delta",
             "path": "/Volumes/main/crm/customers"
           },
           "silver.crm.customers_clean": {
             "format": "delta",
             "write": {
               "mode": "merge",
               "merge": {
                 "keys": [
                   "customer_id"
                 ]
               }
             }
           }
         }

**Registering outputs in Unity Catalog**

An output with ``format: unity_catalog`` is written as a Delta table and
registered as ``<catalog_name>.<schema>.<table>``, where schema and table come
from its three-part name (``silver.crm.customers`` → schema ``silver``, table
``customers``). ``{environment}`` in ``catalog_name`` keeps environments apart:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # catalog.toml
         ["silver.crm.customers"]
         format = "unity_catalog"
         catalog_name = "main_{environment}"
         uc_table_mode = "external"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # catalog.yaml
         silver.crm.customers:
           format: unity_catalog
           catalog_name: "main_{environment}"
           uc_table_mode: external                # external (data at the path) or managed

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "silver.crm.customers": {
             "format": "unity_catalog",
             "catalog_name": "main_{environment}",
             "uc_table_mode": "external"
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
