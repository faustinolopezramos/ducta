.. raw:: html

   <div style="display: flex; align-items: center; justify-content: center; gap: 18px; margin-bottom: 0.5em;">
     <img src="_static/ducta-logo.svg" alt="Ducta" style="width: 55px; height: 55px;">
     <span style="font-size: 2.6em; font-weight: 600; color: var(--color-foreground-primary); letter-spacing: -0.02em;">Ducta</span>
   </div>
   <p style="text-align: center; margin-top: 0; margin-bottom: 1.5em;"><em>Build, run, and trust data pipelines &mdash; batch, streaming, and ML &mdash; from simple configuration.</em></p>

Ducta is a Python framework for building and running data pipelines. You
describe your workflow in a few configuration files and write your
transformations as ordinary Python functions — Ducta handles orchestration,
data quality, and MLOps, so you can focus on **the data**.

.. note::

   You are reading the documentation for Ducta |release| (alpha). The public API
   may change between minor versions until ``1.0.0``.

Start here
==========

.. grid:: 1 2 2 2
   :gutter: 3

   .. grid-item-card:: 🚀 Getting Started
      :link: getting_started
      :link-type: doc

      Install Ducta and run your first pipeline in under five minutes.

   .. grid-item-card:: 📖 Configuration Reference
      :link: configuration
      :link-type: doc

      Global settings, pipelines, nodes, inputs, and outputs — every option explained.

   .. grid-item-card:: 💻 CLI Usage
      :link: cli_usage
      :link-type: doc

      Every command and flag for running pipelines from the terminal.

   .. grid-item-card:: 🧪 Tutorials
      :link: tutorials/index
      :link-type: doc

      End-to-end guides for batch ETL, streaming, and MLOps.

Why Ducta?
==========

Ducta bridges the gap between simple scripts and heavyweight orchestrators.

.. grid:: 1 1 2 2
   :gutter: 3

   .. grid-item::

      .. card:: 📝 Configuration first
         :shadow: md

         Define your whole workflow in clean, versioned YAML / TOML / JSON. No
         hidden dependencies buried in Python decorators.

   .. grid-item::

      .. card:: 🛡️ Quality built in
         :shadow: md

         Automatic data-quality checks, validation, and retries come standard —
         and a *quality gate* can stop a run before bad data spreads.

   .. grid-item::

      .. card:: 🌍 Environment agnostic
         :shadow: md

         Develop locally with CSVs and deploy to Spark or Databricks with a
         simple environment override. Same code, different data.

   .. grid-item::

      .. card:: 🧠 MLOps integrated
         :shadow: md

         Native experiment tracking, a versioned model registry, and
         reproducible splits — not just ETL.

Quick start
===========

Get running in three commands:

.. code-block:: bash

   # 1. Install
   pip install ducta

   # 2. Scaffold a project (Medallion layout: bronze → silver → gold)
   ducta template --template medallion_basic --project-name my_pipeline --format yaml
   cd my_pipeline

   # 3. Run the example pipeline
   ducta start --env base --pipeline etl

✨ **Done!** You just ran your first Ducta pipeline. Next, head to
:doc:`getting_started` to make it your own.

Getting help
============

**New to Ducta?**
   Start with :doc:`installation` and :doc:`getting_started`.

**Building a specific kind of pipeline?**
   See the tutorials: :doc:`tutorials/batch_etl`, :doc:`tutorials/streaming`, or
   :doc:`tutorials/mlops`.

**Questions or a bug?**
   Open an issue on `GitHub <https://github.com/faustinolopezramos/ducta/issues>`_.

.. toctree::
   :maxdepth: 2
   :hidden:
   :caption: 🚀 Getting Started

   installation
   getting_started
   quick_reference

.. toctree::
   :maxdepth: 2
   :hidden:
   :caption: 📖 User Guide

   cli_usage
   configuration
   quality
   streaming
   mlops
   server_api

.. toctree::
   :maxdepth: 2
   :hidden:
   :caption: 🧪 Tutorials

   tutorials/index

.. toctree::
   :maxdepth: 2
   :hidden:
   :caption: 🚀 Deployment

   databricks_setup

.. toctree::
   :maxdepth: 2
   :hidden:
   :caption: 📚 Reference

   best_practices
