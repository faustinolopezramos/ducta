Configuration Guide
===================

Configuration tells Ducta what to do. You describe your pipelines, data sources,
and settings in declarative files — Ducta reads them and runs the work. The
format is up to you: **TOML**, **YAML**, or **JSON** all work, and Ducta detects
the format from the file extension (``.toml``, ``.yaml``, ``.yml``, ``.json``).

.. tip::
   TOML is the recommended default (strict typing, no indentation traps), but
   pick whatever your team is comfortable with. You can even mix formats in the
   same project.

The Five Configuration Files
----------------------------

A Ducta project is described by five files, each with one job:

.. list-table::
   :widths: 28 72
   :header-rows: 1

   * - File
     - What it defines
   * - ``config/global_settings.{ext}``
     - Project-wide settings: paths, execution mode, quality profiles, MLOps.
   * - ``config/pipelines.{ext}``
     - Your workflows — which nodes run, in what order, of what type.
   * - ``config/nodes.{ext}``
     - What each step does: the Python function, its inputs/outputs, checks.
   * - ``config/input.{ext}``
     - The input catalog: where each dataset is read from.
   * - ``config/output.{ext}``
     - The output catalog: where each dataset is written to.

Two more files complete the picture:

- ``environment.{toml,yaml}`` (project root) — a small **descriptor** that tells
  Ducta where the five files live for each environment. ``ducta template``
  generates it for you; you rarely edit it by hand.
- ``.env`` — secrets and machine-local values (passwords, tokens, absolute
  paths). Referenced from config, never committed.

.. important::
   **Every config file is flat — there is no top-level wrapper key.** In
   ``pipelines`` the top-level keys are pipeline names; in ``nodes`` they are
   node names; in ``input``/``output`` they are dataset names. Do **not** nest
   them under a ``pipelines:`` / ``nodes:`` / ``inputs:`` key — Ducta would read
   that wrapper as a pipeline/node/dataset called "pipelines" and fail.

global_settings — project-wide settings
----------------------------------------

Settings live at the top level of the file (flat keys):

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/global_settings.toml
         project_name = "my_project"
         mode = "local"                      # local, databricks, or distributed
         input_path = "data"                 # base dir for ${input_path}
         output_path = "data"                # base dir for ${output_path}
         max_parallel_nodes = 4              # nodes run in parallel where possible
         fail_on_error = true

         # Reusable quality profiles (referenced by nodes via profile = "...")
         [quality.profiles.default]
         checks.empty_dataset = { enabled = true }

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/global_settings.yaml
         project_name: my_project
         mode: local
         input_path: data
         output_path: data
         max_parallel_nodes: 4
         fail_on_error: true

         quality:
           profiles:
             default:
               checks:
                 empty_dataset:
                   enabled: true

   .. tab-item:: JSON

      .. code-block:: json

         {
           "project_name": "my_project",
           "mode": "local",
           "input_path": "data",
           "output_path": "data",
           "max_parallel_nodes": 4,
           "fail_on_error": true,
           "quality": {
             "profiles": {
               "default": {
                 "checks": { "empty_dataset": { "enabled": true } }
               }
             }
           }
         }

pipelines — your workflows
--------------------------

Each top-level key is a pipeline name. Ducta auto-detects the execution engine
from ``type`` (``batch``, ``ml``, ``streaming``, or ``hybrid``) — there is no
CLI layer flag.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/pipelines.toml
         [etl]
         description = "Complete ETL pipeline: Extract -> Transform -> Load"
         type = "batch"
         nodes = ["extract", "transform", "load"]   # execution order
         inputs = ["source_data"]
         outputs = ["gold.etl.final_output"]
         requires_dates = false             # true => --start-date/--end-date required

         [training]
         type = "ml"
         nodes = ["prepare", "train", "evaluate"]
         model_version = "1.0.0"

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/pipelines.yaml
         etl:
           description: "Complete ETL pipeline: Extract -> Transform -> Load"
           type: batch
           nodes: [extract, transform, load]
           inputs: [source_data]
           outputs: [gold.etl.final_output]
           requires_dates: false

         training:
           type: ml
           nodes: [prepare, train, evaluate]
           model_version: "1.0.0"

   .. tab-item:: JSON

      .. code-block:: json

         {
           "etl": {
             "description": "Complete ETL pipeline: Extract -> Transform -> Load",
             "type": "batch",
             "nodes": ["extract", "transform", "load"],
             "inputs": ["source_data"],
             "outputs": ["gold.etl.final_output"],
             "requires_dates": false
           },
           "training": {
             "type": "ml",
             "nodes": ["prepare", "train", "evaluate"],
             "model_version": "1.0.0"
           }
         }

nodes — what each step does
---------------------------

Each top-level key is a node name. A node points at a Python function and
declares the datasets it reads (``input``) and writes (``output``), plus its
upstream ``dependencies``. Optional ``sanity_checks`` (pre-run) and
``data_quality`` (post-run) attach validation — see :doc:`quality`.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/nodes.toml
         [extract]
         module = "pipelines.etl"           # Python module holding the function
         function = "extract"               # function name in that module
         description = "Load data from source"
         input = ["source_data"]
         output = ["bronze.etl.raw_data"]
         dependencies = []
         retry = 3                          # retries on failure
         timeout = 300                      # seconds

         [extract.sanity_checks]
         enabled = true
         fail_fast = true
         profile = "default"                # inherit checks from a global profile
         checks.null_rate = { enabled = true, threshold = 0.1 }

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/nodes.yaml
         extract:
           module: pipelines.etl
           function: extract
           description: "Load data from source"
           input: [source_data]
           output: [bronze.etl.raw_data]
           dependencies: []
           retry: 3
           timeout: 300
           sanity_checks:
             enabled: true
             fail_fast: true
             profile: default
             checks:
               null_rate:
                 enabled: true
                 threshold: 0.1

   .. tab-item:: JSON

      .. code-block:: json

         {
           "extract": {
             "module": "pipelines.etl",
             "function": "extract",
             "description": "Load data from source",
             "input": ["source_data"],
             "output": ["bronze.etl.raw_data"],
             "dependencies": [],
             "retry": 3,
             "timeout": 300,
             "sanity_checks": {
               "enabled": true,
               "fail_fast": true,
               "profile": "default",
               "checks": { "null_rate": { "enabled": true, "threshold": 0.1 } }
             }
           }
         }

.. note::
   ``module`` + ``function`` is the usual form. You can also give a single
   fully-qualified path in ``function`` (e.g. ``function = "pipelines.etl.extract"``)
   and omit ``module``.

input & output — the data catalogs
-----------------------------------

Inputs and outputs live in **separate** files. Each top-level key is a dataset
name that nodes reference in their ``input``/``output`` lists. Filepaths support
variable interpolation (see below).

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/input.toml
         [source_data]
         description = "Source dataset"
         format = "csv"                     # csv, json, parquet, delta, kafka, query
         filepath = "data/input.csv"
         options = { header = true, inferSchema = true }

         # Intermediate datasets are read back through the catalog too
         [bronze.etl.raw_data]
         format = "parquet"
         filepath = "${output_path}/${environment}/bronze/etl/raw_data"

      .. code-block:: toml

         # config/output.toml
         [bronze.etl.raw_data]
         description = "Extracted raw data (bronze layer)"
         format = "parquet"
         write_mode = "overwrite"           # overwrite, append, merge, ignore, error
         filepath = "${output_path}/${environment}/bronze/etl/raw_data"

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/input.yaml
         source_data:
           description: "Source dataset"
           format: csv
           filepath: data/input.csv
           options:
             header: true
             inferSchema: true

         bronze.etl.raw_data:
           format: parquet
           filepath: ${output_path}/${environment}/bronze/etl/raw_data

      .. code-block:: yaml

         # config/output.yaml
         bronze.etl.raw_data:
           description: "Extracted raw data (bronze layer)"
           format: parquet
           write_mode: overwrite
           filepath: ${output_path}/${environment}/bronze/etl/raw_data

   .. tab-item:: JSON

      .. code-block:: json

         {
           "source_data": {
             "description": "Source dataset",
             "format": "csv",
             "filepath": "data/input.csv",
             "options": { "header": true, "inferSchema": true }
           },
           "bronze.etl.raw_data": {
             "format": "parquet",
             "filepath": "${output_path}/${environment}/bronze/etl/raw_data"
           }
         }

Variables & Secrets
-------------------

Config values support interpolation so you never hard-code paths or credentials:

- ``${input_path}`` / ``${output_path}`` / ``${environment}`` — resolved from
  ``global_settings`` and the active ``--env``.
- ``$DB_PASSWORD`` — read from ``.env`` or the process environment.
- ``$TIMEOUT|300`` — use the environment value, or ``300`` if it is not set.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         [source_data]
         format = "query"
         options = { url = "$DB_URL", password = "$DB_PASSWORD" }
         timeout = "$TIMEOUT|300"

   .. tab-item:: YAML

      .. code-block:: yaml

         source_data:
           format: query
           options:
             url: $DB_URL
             password: $DB_PASSWORD
           timeout: $TIMEOUT|300

Put the actual values in ``.env`` (git-ignored):

.. code-block:: bash

   DB_URL=postgresql://db.internal:5432/sales
   DB_PASSWORD=supersecret
   TIMEOUT=600

Environments & Overrides
------------------------

Every Ducta project recognizes the same five canonical environments, and
``--env`` behaves identically no matter which :ref:`configuration form
<project-layouts>` the project uses:

.. list-table::
   :widths: 18 82
   :header-rows: 1

   * - Environment
     - Purpose
   * - ``base``
     - Shared defaults, always loaded first. The implicit fallback for every
       other environment. Default when ``--env`` is omitted.
   * - ``dev``
     - Local development: small data, serial execution, verbose logging.
   * - ``sandbox`` / ``sandbox_<developer>``
     - Pre-prod validation of MLOps/quality changes. ``sandbox_alice``,
       ``sandbox_bob``, ... give each developer an isolated environment that
       falls back to the shared ``sandbox`` settings for anything they don't
       override themselves.
   * - ``staging``
     - Pre-production, full-scale data, mirrors ``prod`` tuning.
   * - ``prod``
     - Production: full datasets, strict quality gates, optimized execution.

``--env`` also accepts common aliases, normalized before resolution:
``production`` → ``prod``, ``development`` → ``dev``, ``test``/``testing`` →
``sandbox``. Any other custom name is accepted as-is (handy for a project-
specific environment your team invents, e.g. ``qa``).

There are two ways to define what changes *between* environments — pick one
per project (they are not combined):

File overrides (canonical form)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``environment.*`` root form. ``ducta template`` scaffolds this by default:

.. code-block:: text

   my_project/
   ├── environment.toml            # maps each env -> its config file paths
   ├── config/
   │   ├── global_settings.toml    # base: shared by every environment
   │   ├── pipelines.toml          # base only (pipelines/nodes are not per-env)
   │   ├── nodes.toml
   │   ├── input.toml
   │   ├── output.toml
   │   ├── dev/                     # dev overrides: global_settings / input / output
   │   ├── sandbox/
   │   └── prod/
   └── .env

- The **base** config lives directly under ``config/`` and is always loaded.
- ``config/dev/``, ``config/sandbox/``, ``config/prod/`` override only
  ``global_settings``, ``input``, and ``output`` — ``pipelines`` and ``nodes``
  are defined once, in base, and shared across every environment.
- The ``environment`` descriptor wires env names to those paths, so you select
  one with ``--env``:

.. code-block:: bash

   ducta start --env dev  --pipeline etl    # base + dev overrides
   ducta start --env prod --pipeline etl    # base + prod overrides

- Requesting an environment that isn't declared in ``env_config`` (after alias
  normalization) fails fast with a clear error listing what *is* declared —
  there is no silent fallback to base here, since a missing file usually means
  a typo or an incomplete scaffold.

.. tip::
   Add per-developer sandboxes with
   ``ducta template ... --sandbox-developers alice bob``, which creates
   ``config/sandbox_alice/`` etc., selectable via ``--env sandbox_alice``.

Inline overrides (bundle / directory-convention / quickstart / layered forms)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The lighter-weight forms keep one ``global_settings`` (however it's packaged)
and carry an inline ``environments:`` block of minimal per-env diffs:

.. code-block:: yaml

   max_parallel_nodes: 4
   mlops_enabled: true
   environments:
     dev:     {max_parallel_nodes: 1, mlops_enabled: false, log_level: DEBUG}
     sandbox: {max_parallel_nodes: 2}
     prod:    {mlops_required: true, max_parallel_nodes: 8}

- ``--env dev`` deep-merges the ``dev`` block over the base settings; a key a
  block omits keeps its base value.
- No block for the requested environment (and it isn't ``base``, which never
  needs one) → Ducta logs a **warning** naming the declared keys, and runs with
  base settings only. This is the mechanism's way of catching a typo in
  ``--env`` or in the block's keys — nothing fails silently.
- ``sandbox_<developer>`` falls back to the generic ``sandbox`` entry when no
  per-developer key exists, same as the file-override form.
- The ``environments:`` key itself is stripped after resolution, so it never
  leaks into the running settings or ``${var}`` interpolation.

.. note::
   Both mechanisms share one normalization layer
   (:mod:`ducta.config.environments`), so alias handling, ``sandbox_<dev>``
   fallback, and the set of recognized environment names are identical
   regardless of which form a project uses.

.. _project-layouts:

Project Layouts (Choosing a Configuration Form)
-----------------------------------------------

The five files above are the *content* of a configuration; how you **lay them
out on disk** is flexible. ``ducta start`` accepts several forms, so you can
trade boilerplate for structure depending on the project's size. All of them
carry the same flat sections — only the packaging changes.

.. list-table::
   :widths: 22 12 66
   :header-rows: 1

   * - Form
     - Files
     - When to use it
   * - **environment root** *(canonical)*
     - 5 + 1
     - Production and anything multi-environment. An ``environment.{toml,yaml}``
       root maps each ``--env`` to the five file paths (see *Environments &
       Overrides* above). Recommended default; ``ducta template`` scaffolds it.
   * - **Bundle**
     - 1
     - Prototypes, demos, examples. One file holds all five sections inline.
   * - **Directory convention**
     - 5
     - A clean five-file split with *no* ``environment.*`` root — Ducta finds the
       files by their standard names.
   * - **Quickstart**
     - 2
     - Smallest real split: a ``global.*`` plus one grouped ``pipeline.*`` file.
   * - **Layered (multi-layer)**
     - per layer
     - Medallion / multi-stage projects. A ``ducta.yaml`` manifest declares
       layers, each with its own five-file config. See *Layered Projects* below.

.. note::
   Environment overrides work in **every** form: keep an inline ``environments:``
   block in your global settings and Ducta deep-merges the active ``--env`` over
   the base (the ``config/dev/`` override *directories* are specific to the
   canonical environment-root form).

Bundle — everything in one file
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A single ``ducta.*``, ``config.*``, or ``bundle.*`` file whose top level carries
the five ``*_config`` sections. This is the one place the sections are *wrapped*
(under ``global_settings`` / ``pipelines_config`` / ...), because they share a
file:

.. code-block:: yaml

   # ducta.yaml  — run:  ducta start --env dev --pipeline demo
   global_settings:
     input_path: ./data
     output_path: ./data
     mode: local
     environments:                 # inline per-env overrides (deep-merged)
       dev: { max_parallel_nodes: 1, log_level: DEBUG }
   pipelines_config:
     demo: { type: batch, requires_dates: false, nodes: [extract] }
   nodes_config:
     extract: { function: etl.extract, input: [raw], output: [processed] }
   input_config:
     raw: { format: parquet, filepath: ./data/raw.parquet }
   output_config:
     processed: { format: parquet, filepath: ./data/processed.parquet }

Directory convention — five files, no root
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Drop the five standard files in the project root or a ``config/`` subdirectory
and skip the ``environment.*`` descriptor entirely. Ducta locates each by name
(``global_settings`` *or* ``global``, ``pipelines``, ``nodes``, ``input``,
``output``). The global file may sit at the root with the rest under ``config/``:

.. code-block:: text

   my_project/
   ├── global.yaml                 # or config/global_settings.yaml
   └── config/
       ├── pipelines.yaml
       ├── nodes.yaml
       ├── input.yaml
       └── output.yaml

Quickstart — two files
~~~~~~~~~~~~~~~~~~~~~~~~

The lightest real split: a ``global.*`` file plus one ``pipeline.*`` file that
groups the remaining four sections under ``pipelines`` / ``nodes`` / ``input`` /
``output`` keys.

.. code-block:: yaml

   # global.yaml
   input_path: ./data
   output_path: ./data
   mode: local

.. code-block:: yaml

   # pipeline.yaml
   pipelines:
     demo: { type: batch, requires_dates: false, nodes: [extract] }
   nodes:
     extract: { function: etl.extract, input: [raw], output: [processed] }
   input:
     raw: { format: parquet, filepath: ./data/raw.parquet }
   output:
     processed: { format: parquet, filepath: ./data/processed.parquet }

Layered Projects (multi-layer)
------------------------------

For medallion-style projects (bronze → silver → gold → ml) each layer is a
self-contained five-file config, and a ``ducta.yaml`` manifest at the root
declares the layers, their locations, and dependencies:

.. code-block:: yaml

   # ducta.yaml
   project:
     type: layered
   layers:
     bronze:  { path: bronze,  config: bronze/config,  dependencies: [] }
     silver:  { path: silver,  config: silver/config,  dependencies: [bronze] }
     gold:    { path: gold,    config: gold/config,    dependencies: [silver] }
     ml:      { path: ml,      config: ml/config,      dependencies: [gold] }
   execution:
     order: [bronze, silver, gold, ml]

Run a single layer explicitly, or let Ducta route by pipeline name:

.. code-block:: bash

   ducta start --layer silver --env dev --pipeline worldcup.silver
   ducta start --env dev --pipeline worldcup.silver     # auto-routes to its layer

.. tip::
   The medallion names ``bronze/silver/gold/ml`` are auto-detected even without a
   manifest (any directory with a ``global.yaml`` + ``config/``). A ``ducta.yaml``
   is only required for **custom** layer names or an explicit execution order.

Best Practices
--------------

- ✅ Keep secrets in ``.env``; reference them with ``$VAR`` — never commit them.
- ✅ Define ``pipelines`` and ``nodes`` once in base; put only environment-specific
  paths and settings in the ``dev``/``prod`` overrides.
- ✅ Use ``${input_path}`` / ``${output_path}`` / ``${environment}`` so the same
  config runs locally and in the cloud unchanged.
- ✅ Give datasets stable, descriptive names (e.g. ``silver.sales.clean``) and
  reuse them across nodes.
- ✅ Validate before running: ``ducta config validate`` and
  ``ducta start --validate-only`` (see :doc:`cli_usage`).
