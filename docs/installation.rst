Installation
============

Ducta is designed to be lightweight and modular. You can install the core engine or include specific modules for your workflow (APIs, Spark, MLOps, etc.).

Requirements
------------

* **Python**: 3.10, 3.11, or 3.12 (Support for 3.13 is in progress)
* **Package Manager**: ``pip``, ``conda``, or ``poetry``
* **OS**: Linux, macOS, or Windows

Standard Installation
---------------------

Install the core Ducta engine using pip:

.. code-block:: bash

   pip install ducta

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
     - Spark + PyArrow support for distributed data processing.
   * - ``ducta[api]``
     - FastAPI server, dashboard backend, and orchestration API.
   * - ``ducta[mlops]``
     - MLflow-backed experiment tracking, model registry, and Databricks Connect.
   * - ``ducta[database]``
     - SQL database drivers (PostgreSQL, async SQLAlchemy) for ingestion/persistence.
   * - ``ducta[monitoring]``
     - Prometheus metrics for observability.
   * - ``ducta[optimization]``
     - NumPy + scikit-optimize for hyperparameter sweeps.
   * - ``ducta[all]``
     - Install every optional feature and connector.

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
