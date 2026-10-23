Deployment and Cloud Environments Guide
========================================

This guide provides instructions for deploying and running Ducta in the two standard operating models:

1. **Model 1: Shared Central Cloud Server** (enterprise team hub hosted on AWS, Azure, or GCP).
2. **Model 2: Local Developer Workstation** (running ``ducta ui`` on a local machine connected to cloud data).

.. contents:: Table of Contents
   :depth: 2
   :local:

Model Comparison
----------------

.. list-table::
   :widths: 25 35 40
   :header-rows: 1

   * - Dimension
     - Model 1: Central Cloud Server
     - Model 2: Local Developer Workstation
   * - **Target Audience**
     - Data teams, shared execution, production orchestration
     - Individual engineers during interactive development
   * - **UI Access**
     - Web browser (``https://ducta.company.com``) with JWT auth
     - Local browser (``http://localhost:8000``), no login required
   * - **Git Repositories**
     - Cloned by server via SSH keys or service PATs
     - Cloned locally using developer's local Git credentials
   * - **Cloud Storage Access**
     - Machine IAM roles (AWS Instance Profile, Azure Managed Identity)
     - Local developer CLI sessions (``aws configure``, ``az login``)
   * - **History Persistence**
     - Shared PostgreSQL database via ``DATABASE_URL``
     - Local SQLite database (``~/.ducta/executions.db``)

---

Model 1: Shared Central Cloud Server
------------------------------------

In this model, Ducta runs as a central service inside an enterprise virtual network (VPC/VNet). Team members connect through their web browsers to review pipelines, inspect DAGs, run jobs, and review execution certificates.

Docker Container Setup
~~~~~~~~~~~~~~~~~~~~~~

A production ``Dockerfile`` packaging Ducta with cloud connectors:

.. code-block:: dockerfile

   FROM python:3.11-slim

   RUN apt-get update && apt-get install -y --no-install-recommends \
       git \
       openssh-client \
       curl \
       ca-certificates \
       && rm -rf /var/lib/apt/lists/*

   WORKDIR /app

   # ducta[api] already brings the PostgreSQL drivers (asyncpg, psycopg2-binary).
   # The cloud packages serve `ducta quality run`/`ducta profile` and an S3 run
   # lock — see
   # "Cloud Storage Access" below for Spark.
   RUN pip install --no-cache-dir \
       "ducta[api]" \
       "boto3" \
       "s3fs" \
       "adlfs" \
       "gcsfs"

   RUN mkdir -p /root/.ducta /root/.ssh

   EXPOSE 8000

   CMD ["ducta", "server", "start", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]

Compose Configuration
~~~~~~~~~~~~~~~~~~~~~

``docker-compose.yml`` running Ducta alongside PostgreSQL:

.. code-block:: yaml

   version: "3.8"

   services:
     postgres:
       image: postgres:16-alpine
       restart: always
       environment:
         POSTGRES_DB: ducta
         POSTGRES_USER: ducta_admin
         POSTGRES_PASSWORD: strong_db_password
       volumes:
         - pgdata:/var/lib/postgresql/data

     ducta:
       build: .
       restart: always
       ports:
         - "8000:8000"
       environment:
         - ENVIRONMENT=production
         - AUTH_ENABLED=true
         - JWT_SECRET_KEY=generate_a_long_random_secret_key_here
         - DUCTA_ADMIN_PASSWORD=choose_a_strong_admin_password   # required in production; "admin" is refused
         - DATABASE_URL=postgresql+asyncpg://ducta_admin:strong_db_password@postgres:5432/ducta
         - CORS_ORIGINS=https://ducta.company.com   # a list: comma-separated or JSON
         - RATE_LIMIT_ENABLED=true
         # Exact host names: Azure DevOps clones over SSH from ssh.dev.azure.com,
         # over HTTPS from dev.azure.com.
         - GIT_CLONE_ALLOWED_HOSTS=ssh.dev.azure.com,dev.azure.com,github.com,git-codecommit.us-east-1.amazonaws.com,gitlab.com
       volumes:
         - ducta_data:/root/.ducta
         - /etc/ducta/ssh:/root/.ssh:ro
       depends_on:
         - postgres

   volumes:
     pgdata:
     ducta_data:

Enterprise Git Repositories Setup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The central server needs permissions to clone and pull from your Git provider:

1. **Generate an SSH key pair on the host**:

   .. code-block:: bash

      ssh-keygen -t ed25519 -C "ducta-server@company.com" -f /etc/ducta/ssh/id_ed25519 -N ""

2. **Register the public key with your provider**:
   - **Azure DevOps**: *User Settings* → *SSH Public Keys* → *New Key*.
   - **AWS CodeCommit**: *IAM Console* → *Users* → *Security credentials* → *SSH public keys for AWS CodeCommit*. Record the generated **SSH Key ID**.
   - **GitHub / GitLab Enterprise**: Repository *Deploy Keys* or organization bot user.

3. **Configure ``/etc/ducta/ssh/config``**:

   .. code-block:: text

      Host ssh.dev.azure.com
        IdentityFile /root/.ssh/id_ed25519
        StrictHostKeyChecking accept-new

      Host git-codecommit.*.amazonaws.com
        User <YOUR_IAM_SSH_KEY_ID>
        IdentityFile /root/.ssh/id_ed25519
        StrictHostKeyChecking accept-new

      Host github.com
        IdentityFile /root/.ssh/id_ed25519
        StrictHostKeyChecking accept-new

Cloud Storage Access (IAM)
~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not store static cloud keys in containers. Assign cloud IAM roles to the host:

- **Amazon AWS**: Assign an **IAM Instance Profile** (EC2) or **IRSA** (EKS) with permissions on your S3 buckets.
- **Microsoft Azure**: Enable **Managed Identity** on the VM or Container App and assign the **Storage Blob Data Contributor** role on the storage account.
- **Google Cloud**: Assign an IAM **Service Account** with **Storage Object Admin** permissions to the Compute Engine instance.

Ducta hands a dataset's URI to the engine as written, so what reads it depends on
where pipelines run:

- **Local Spark** (``settings.mode: local``, what a server runs by default) has no
  cloud filesystem built in: ``s3://`` fails with *No FileSystem for scheme "s3"*.
  Add your cloud's Hadoop connector to ``settings.spark_config``
  (``spark.jars.packages``, e.g. ``org.apache.hadoop:hadoop-aws`` for ``s3a://``)
  and use its scheme.
- **Databricks** reads ``s3://``, ``abfss://`` and ``gs://`` natively.
- ``ducta quality run`` and ``ducta profile`` read their ``--input`` file with
  pandas, through fsspec: ``s3fs``, ``adlfs`` or ``gcsfs``.

``boto3`` is needed only for a run lock kept on S3
(``settings.run_lock: {backend: storage, dir: s3://…}``).

.. code-block:: yaml

   silver.sales.orders:
     format: parquet
     path: s3a://company-datalake/silver/sales/orders/

---

Model 2: Local Developer Workstation
-------------------------------------

In this model, developers run Ducta locally to build, test, and debug pipelines interactively.

Installation
~~~~~~~~~~~~

.. code-block:: bash

   # Create and activate environment
   python3 -m venv .venv
   source .venv/bin/activate

   # Install Ducta with Web UI
   pip install "ducta[api]"

   # Optional: cloud filesystems for `ducta quality run` / `ducta profile`
   # (pipelines on Spark need its connector — see "Cloud Storage Access" above)
   pip install s3fs             # AWS S3
   pip install adlfs            # Azure Data Lake Storage Gen2
   pip install gcsfs            # Google Cloud Storage

Local Cloud Authentication
~~~~~~~~~~~~~~~~~~~~~~~~~~

Log in with your corporate cloud CLI:

.. code-block:: bash

   # AWS
   aws configure
   # or with SSO:
   aws sso login --profile company-profile

   # Azure
   az login

   # Google Cloud
   gcloud auth application-default login

Starting the UI
~~~~~~~~~~~~~~~

Run ``ducta ui`` from your project directory or specify a target:

.. code-block:: bash

   cd ~/projects/sales_pipeline
   ducta ui

The browser opens automatically at ``http://localhost:8000``.

Connecting Workspaces
~~~~~~~~~~~~~~~~~~~~~

At ``http://localhost:8000/setup``:

- **Local folder**: Select an existing repository already cloned on your machine.
- **Git repository**: Paste the SSH URL of your repository (e.g. ``git@ssh.dev.azure.com:...`` or ``git@github.com:...``). Ducta automatically leverages your personal SSH agent (``~/.ssh/``).

Daily Workflow
~~~~~~~~~~~~~~

1. **Interactive DAG & Code Editor**: Edit pipelines and their code. Type checking
   and completions come from a Python language server when one is installed
   (``basedpyright``, ``pyright`` or ``python-lsp-server``; ``LSP_COMMAND`` picks one).
2. **Sample Runs**: select a node and press *Sample* (or ⌘/Ctrl+Enter in its code)
   to run it on the first 100 rows of each input; outputs go to ``.ducta/scratch``,
   never to the real datasets.
3. **Preflight Checks**: Verify DAG consistency and data contracts in the *Problems* dock.
4. **Git Sync**: Stage and commit from the ``/workspace/git`` page. Pull and push
   there need a workspace opened from a Git URL; for a local folder, pull and push
   from a terminal.
