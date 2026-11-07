Installation
============

Ducta is designed to be lightweight and modular. You can install the core engine or include specific modules for your workflow (APIs, Spark, MLOps, etc.).

Requirements
------------

* **Python**: 3.11, 3.12, 3.13 or 3.14
* **Spark**: 3.5 or 4.2 (``ducta[spark]`` installs 4.2). Python 3.14 needs Spark 4.
* **Java**: a JDK 17 or 21 for the ``spark`` extra (Spark 4 does not start on older
  ones; Spark 3.5 runs Arrow only on 17)
* **Package Manager**: ``pip``, ``conda``, or ``poetry``
* **OS**: Linux, macOS, or Windows

``ducta check`` (and the start of a local Spark session) warns about combinations known
not to work — Spark 3.5 on Python 3.14, Spark 4 on Java 11, pandas 3 — with the fix.

To stay on Spark 3.5, pin it: ``pip install "ducta[spark,delta]" "pyspark>=3.5,<3.6"``
(pip then picks the Delta release for 3.5).

Two Spark defaults change results, and Ducta leaves both to the project. It warns
while ``settings.spark_config`` does not set them, to either value:

* **ANSI mode** (``spark.sql.ansi.enabled``), on by default in Spark 4: an invalid
  ``CAST``, a division by zero or an overflow stops the run, where Spark 3.5 returned
  ``NULL`` (or, for an overflow, a wrapped-around number). ``"false"`` keeps the Spark 3.5
  behaviour; ``"true"`` keeps the error.
* **The session time zone** (``spark.sql.session.timeZone``), by default the machine's:
  the same pipeline can compute other dates, timestamps and date partitions on a laptop
  and on a server. Set it, for example to ``UTC``.

.. code-block:: yaml

   settings:
     spark_config:
       spark.sql.ansi.enabled: "true"
       spark.sql.session.timeZone: UTC

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

Reproducible installs
~~~~~~~~~~~~~~~~~~~~~

``pip`` installs the newest versions every range allows, so two installs a month
apart can differ. Each release attaches the exact versions it was tested with, one
file per Python, to its `GitHub release
<https://github.com/faustinolopezramos/ducta/releases>`_:

.. code-block:: bash

   pip install "ducta[all]==X.Y.Z" \
     -c https://github.com/faustinolopezramos/ducta/releases/download/vX.Y.Z/constraints-py3.13.txt

Put the version you install and your Python in the command. Releases published
before Ducta supported Python 3.14 have no constraints files.

Supported versions
------------------

Ducta supports the versions their own projects still support:

* **Python**: every version that has not reached its end of life, from the first
  Ducta release after it comes out. A version is dropped in the first minor release
  after its end of life (Python 3.10 ended in October 2026, and is no longer supported).
* **Spark**: the lines Apache still maintains and Delta Lake builds for — today 3.5
  (until November 2027) and 4.2. A new Spark line is added once Delta Lake ships a
  build for it.
* **Java**: the JDKs those Spark lines support (17 and 21).

Every change of this list is announced under *Changed (breaking)* in the
`changelog <https://github.com/faustinolopezramos/ducta/blob/main/CHANGELOG.md>`_.
A weekly job tests the newest release of every dependency, so a release that breaks
Ducta is found before a user finds it.

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
