Tutorials
=========

.. toctree::
   :maxdepth: 2

   basic_examples
   batch_etl
   streaming
   mlops
   certificates
   airflow_integration
   fastapi_integration

Overview
--------

These tutorials provide hands-on examples of using Ducta for various use cases.

Batch ETL Tutorial
~~~~~~~~~~~~~~~~~~

Learn how to build a complete batch ETL pipeline with the Medallion architecture (Bronze → Silver → Gold).

Topics covered:

- Data ingestion from multiple sources
- Data cleaning and validation
- Business metric calculation
- Partitioning and optimization

:doc:`batch_etl`

Streaming Tutorial
~~~~~~~~~~~~~~~~~~

Build real-time streaming pipelines with Kafka and Kinesis.

Topics covered:

- Kafka integration
- Checkpointing and recovery
- Stream monitoring
- Error handling

:doc:`streaming`

MLOps Tutorial
~~~~~~~~~~~~~~

Implement ML workflows with experiment tracking and model management.

Topics covered:

- Experiment tracking
- Model registry
- Model deployment
- Pipeline automation

:doc:`mlops`

Run Certificates
~~~~~~~~~~~~~~~~~

Prove what a pipeline run actually did: what ran, against which data, with
what result — and how to tell a real guarantee from a weaker one.

Topics covered:

- Certificate anatomy and the three levels of proof (hash, signature, ``--reproduce``)
- Configuring signing and fingerprint modes
- The ``ducta certify`` CLI: ``list``, ``show``, ``verify``, ``diff``
- Comparing certificates written by different fingerprint algorithms

:doc:`certificates`

Airflow Integration
~~~~~~~~~~~~~~~~~~~

Orchestrate Ducta pipelines with Apache Airflow.

Topics covered:

- DAG creation
- Task dependencies
- Error handling
- Monitoring

:doc:`airflow_integration`

FastAPI Integration
~~~~~~~~~~~~~~~~~~~

Build REST APIs for pipeline execution.

Topics covered:

- API endpoints
- Async execution
- Status tracking
- Authentication

:doc:`fastapi_integration`

Prerequisites
-------------

For all tutorials, you should have:

- Ducta installed (``pip install ducta[all]``)
- Basic Python knowledge
- Familiarity with data processing concepts

Optional:

- Apache Spark knowledge (for optimization)
- Docker (for some tutorials)
- Cloud account (for deployment tutorials)

Getting Help
------------

If you get stuck:

1. Ask in `GitHub Discussions <https://github.com/faustinolopezramos/ducta/discussions>`_
2. Report issues on `GitHub Issues <https://github.com/faustinolopezramos/ducta/issues>`_
