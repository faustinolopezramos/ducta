Installation
============

Ducta is designed to be lightweight and modular. You can install the core engine or include specific modules for your workflow (APIs, Spark, MLOps, etc.).

Requirements
------------

* **Python**: 3.10, 3.11, 3.12 or 3.13
* **Java**: a JDK for the ``spark`` extra — 17 is the one PySpark 3.5 supports fully
* **Package Manager**: ``pip``, ``conda``, or ``poetry``
* **OS**: Linux, macOS, or Windows

Standard Installation
---------------------

Install Ducta with the Spark extra, which pipelines run on:

.. code-block:: bash

   pip install "ducta[spark]"

``pip install ducta`` alone installs the core: ``ducta template``, ``ducta config``
and ``ducta certify`` work, but running a pipeline needs ``spark``.

Verified Installation
~~~~~~~~~~~~~~~~~~~~~

After installation, verify that the CLI is correctly mapped to your path:

.. code-block:: bash

   ducta --version

Modular Extras
--------------

Ducta follows a "pay-for-what-you-use" approach with its dependencies. You can install extra features as needed:

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - Extra
     - Description
   * - ``ducta[spark]``
     - PySpark and PyArrow: the engine pipelines run on.
   * - ``ducta[delta]``
     - Delta Lake for local Spark (``delta-spark``): Delta reads, writes and ``merge``.
   * - ``ducta[api]``
     - The server and web app (``ducta ui``): FastAPI, persistence drivers, Git,
       Redis for shared rate limits.
   * - ``ducta[database]``
     - SQL drivers (SQLAlchemy, PostgreSQL, SQLite) on their own.
   * - ``ducta[mlops]``
     - MLflow, scikit-learn, NumPy, SciPy and Optuna: tracking, the model
       registry and hyperparameter search.
   * - ``ducta[boost]``
     - XGBoost and LightGBM.
   * - ``ducta[ai]``
     - The AI pipeline builder (``ducta ai``): httpx, the Anthropic SDK, keyring
       and ruamel.yaml (edits YAML keeping its comments).
   * - ``ducta[monitoring]``
     - Prometheus metrics.
   * - ``ducta[databricks]``
     - Databricks Connect. Not part of ``all``: it replaces PySpark, so install
       it in an environment of its own.
   * - ``ducta[all]``
     - Every extra above except ``databricks``.

Example:

.. code-block:: bash

   pip install "ducta[mlops,spark]"

Professional Setup (Recommended)
--------------------------------

For production environments or local development, we highly recommend using a virtual environment to avoid dependency conflicts.

Using venv
~~~~~~~~~~

.. tab-set::

   .. tab-item:: Linux / macOS

      .. code-block:: bash

         python3 -m venv .vh
         source .vh/bin/activate
         pip install --upgrade pip
         pip install ducta

   .. tab-item:: Windows (PowerShell)

      .. code-block:: powershell

         python -m venv .vh
         .\.vh\Scripts\Activate.ps1
         python -m pip install --upgrade pip
         pip install ducta

Using Conda
~~~~~~~~~~~

.. code-block:: bash

   conda create -n ducta_env python=3.11
   conda activate ducta_env
   pip install ducta

Troubleshooting
---------------

Common issues during installation:

* **Command not found**: Ensure your Python scripts folder is in your system PATH.
* **Architecture mismatch**: If using Apple Silicon (M1/M2/M3), ensure you are using an ARM64 version of Python.
* **Proxy issues**: If behind a corporate firewall, use ``--proxy`` or set your ``HTTP_PROXY`` environment variables.

Next: :doc:`getting_started`
