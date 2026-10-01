Basic Examples
==============

Small, complete projects that show one idea each. Every one runs as written:
create the files, then run the command at the end of the section.

A first pipeline
----------------

Read a CSV, keep adults, write Parquet.

.. code-block:: text

   hello/
   ├── ducta.yaml
   ├── catalog.yaml
   ├── data/users.csv
   └── pipelines/
       ├── __init__.py
       ├── people.yaml
       └── people.py

.. code-block:: yaml

   # ducta.yaml
   version: 2
   project: hello
   paths: {input: data, output: data}

.. code-block:: yaml

   # catalog.yaml
   users:
     format: csv
     path: ${paths.input}/users.csv
     options: {header: true, inferSchema: true}
   silver.people.adults:
     format: parquet

.. code-block:: yaml

   # pipelines/people.yaml
   requires_dates: false
   nodes:
     keep_adults:
       run: pipelines.people:keep_adults
       inputs: {users: users}
       outputs: [silver.people.adults]

.. code-block:: python

   # pipelines/people.py
   from pyspark.sql import DataFrame, functions as F


   def keep_adults(users: DataFrame) -> DataFrame:
       return users.filter(F.col("age") >= 18)

.. code-block:: text

   # data/users.csv
   id,name,age
   1,Ana,34
   2,Luis,15
   3,Marta,52

.. code-block:: bash

   cd hello
   ducta config validate
   ducta start --pipeline people

The output lands in ``data/base/silver/people/adults`` — the conventional
location of a three-part name under the ``base`` environment. ``--env dev``
would write ``data/dev/…`` instead.

Two inputs, one output
----------------------

Each input is passed to the function parameter it is mapped to:

.. code-block:: yaml

   # pipelines/orders.yaml
   requires_dates: false
   nodes:
     enrich:
       run: pipelines.orders:enrich
       inputs: {orders: orders_raw, customers: customers_raw}
       outputs: [silver.sales.orders_enriched]

.. code-block:: python

   # pipelines/orders.py
   from pyspark.sql import DataFrame


   def enrich(orders: DataFrame, customers: DataFrame) -> DataFrame:
       return orders.join(customers, "customer_id", "left")

Steps that depend on each other
-------------------------------

A node that reads what another writes runs after it — no ordering to declare:

.. code-block:: yaml

   # pipelines/daily.yaml
   requires_dates: false
   nodes:
     clean:
       run: pipelines.daily:clean
       inputs: {orders: orders_raw}
       outputs: [silver.sales.orders]
     totals:
       run: pipelines.daily:totals
       inputs: {orders: silver.sales.orders}   # runs after `clean`
       outputs: [gold.sales.daily_totals]
     notify:
       run: pipelines.daily:notify
       inputs: {totals: gold.sales.daily_totals}
     audit:
       run: pipelines.daily:audit
       after: [clean]                          # no data between them: order it explicitly

Pipelines that depend on each other
-----------------------------------

``depends_on`` runs whole pipelines first. With ``--reuse-upstream``, an
upstream whose outputs are still valid for the same inputs, dates, code and
configuration is not recomputed:

.. code-block:: yaml

   # pipelines/reporting.yaml
   depends_on: [daily]
   requires_dates: false
   nodes:
     report:
       run: pipelines.reporting:report
       inputs: {totals: gold.sales.daily_totals}
       outputs: [gold.sales.report]

.. code-block:: bash

   ducta start --pipeline reporting --reuse-upstream

A date window
-------------

With ``requires_dates: true`` (the default) a run takes a window, and an
``incremental`` dataset is read — and fingerprinted — only inside it:

.. code-block:: yaml

   # catalog.yaml
   events:
     format: parquet
     path: ${paths.input}/events
     incremental: {column: event_date}

.. code-block:: bash

   ducta start --pipeline daily --start-date 2026-03-01 --end-date 2026-03-01

A check that stops bad data
---------------------------

.. code-block:: yaml

   # pipelines/people.yaml
   requires_dates: false
   nodes:
     keep_adults:
       run: pipelines.people:keep_adults
       inputs: {users: users}
       outputs: [silver.people.adults]
       quality:
         checks:
           null_rate: {columns: [id], threshold: 0}
           row_count: {min: 1}
         gate: {on_fail: stop_all}

If the output has a null ``id`` or no rows, the run stops and fails, and the
Run Certificate records which check blocked it. See :doc:`../quality`.

Next steps
----------

- :doc:`batch_etl` — a medallion pipeline end to end
- :doc:`../configuration` — every key of every file
