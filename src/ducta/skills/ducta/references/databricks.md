# Running on Databricks

Needs `pip install "ducta[databricks]"` (Databricks Connect). Ducta runs the pipeline
through a Databricks Connect session on a cluster; provisioning the workspace and
cluster is the user's responsibility.

## 1. Credentials: environment only

Ducta does not read Databricks host/token/cluster from its own files. Set the standard
variables (shell or `.env`, never committed):

```bash
DATABRICKS_HOST=https://<workspace>.cloud.databricks.com
DATABRICKS_TOKEN=…
DATABRICKS_CLUSTER_ID=…
```

or a `~/.databrickscfg` profile with `DATABRICKS_CONFIG_PROFILE`. Host, token and
cluster id are all required. Never write the token into a project file.

## 2. Mode and paths, usually for prod only

```yaml
# ducta.yaml
settings: {mode: local}
environments:
  prod:
    settings: {mode: databricks}
    paths:
      input: /Volumes/main/sales/input
      output: /Volumes/main/sales/output
```

## 3. Run

```bash
ducta config validate --env prod --output-format json
ducta start --env prod --pipeline my_pipeline        # only when the user asks to run prod
```

## Datasets

Delta is read and written by **path** (Volumes, `dbfs:/`, a cloud URI), not by a
`catalog.schema.table` identifier:

```yaml
customers:
  format: delta
  path: /Volumes/main/crm/customers
```

To register an output in Unity Catalog:

```yaml
silver.crm.customers:
  format: unity_catalog
  catalog_name: "main_{environment}"   # keeps environments apart
  uc_table_mode: external              # or managed
```

The table becomes `<catalog_name>.<schema>.<table>` from the three-part name.

## Common problems

| Symptom | Fix |
|---|---|
| configuration error at session creation | one of `DATABRICKS_HOST`/`TOKEN`/`CLUSTER_ID` is missing |
| authentication failed | token expired or without permissions; check the host format (`https://…`) |
| cluster not found / not running | check the id; start the cluster |
| path not found | use full Volumes paths `/Volumes/<catalog>/<schema>/<volume>/…` and check permissions |
| `databricks.connect` not found | `pip install "ducta[databricks]"` with a version matching the cluster runtime |
