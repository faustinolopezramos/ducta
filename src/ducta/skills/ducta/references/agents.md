# Ducta's agents: Architect and Sentinel

Two agents ship with Ducta. **Rules decide, the model proposes:** what can break
data is checked or decided by Ducta's code; a model only designs, writes function
bodies, explains and drafts. Nothing is applied without `ducta ai apply`, nothing
is committed, nothing runs in a protected environment (`prod`).

| | Ducta Architect | Ducta Sentinel |
|---|---|---|
| Does | designs new pipelines as a blueprint, builds them as a draft | opens incidents for failed, late, slow runs; safe re-runs; proposals |
| CLI | `ducta ai architect …` | `ducta ai sentinel …` |
| Needs a model | `plan`, `build` (not `check`, `scaffold`, `verify`) | only for L2 proposals |
| As an assistant's agent | `ducta-architect` | `ducta-sentinel` (reads, never edits) |

`ducta skill install --agents` also installs both as agent definitions for Claude
Code (`.claude/agents/`; `--global` for every project); any assistant can follow
this page and the commands below instead.

## Architect

```bash
ducta ai architect plan "revenue per store and day"     # the model writes a blueprint (a draft)
ducta ai revise DRAFT_ID --note "keep refunds out"       # ask for changes
ducta ai architect check blueprint.yaml --output-format json   # no model: Ducta's verdict
ducta ai architect scaffold blueprint.yaml               # no model: a draft with stub functions
ducta ai architect build DRAFT_ID                        # the model writes each module
ducta ai apply DRAFT_ID                                  # review, then write
ducta ai architect verify silver.stores gold.stores --run --tests   # validate, run in dev, snapshot
```

A blueprint names everything and writes the logic in words; Ducta writes every
YAML file from it, and a `quality` block per output from its contract:

```yaml
name: store_revenue
goal: Revenue per store and day
assumptions: [store_id is the first three characters of order_id]
datasets:                         # only NEW datasets; reuse the catalog's as inputs
  silver.sales.orders_by_store:
    description: One row per order with its store
    format: delta                 # omit to use the project's default for the layer
    keys: [order_id]
    write: merge                  # overwrite | merge (keys + delta) | append (avoid)
    columns: {order_id: bigint, store_id: string, amount: double}
    not_null: [order_id, store_id]
    unique: [order_id]
    pii: []
pipelines:                        # only NEW pipelines, named <layer>.<domain>
  silver.stores:
    description: Attach stores to orders
    owner: data-team
    nodes:
      orders_with_store:
        inputs: {orders: silver.sales.orders}     # parameter -> dataset
        outputs: [silver.sales.orders_by_store]   # exactly one
        logic: store_id is the first three characters of order_id
```

`check` refuses: an existing pipeline, node or dataset name; an input that is
neither in the catalog nor in the blueprint; a dataset with two writers or none;
data flowing to a lower layer; `merge` without `keys` or not on Delta; an ingest
node whose source is not in `sources.yaml`. Then it validates the rendered files
like any draft. `build` accepts a module only with exactly the functions and
parameters the blueprint implies, and without I/O of its own, `collect()` or a
credential. A blueprint draft is never applied; the draft `build` makes is.

## Sentinel

Off until the project enables it in `ducta.yaml`:

```yaml
sentinel:
  enabled: true
  environments: [dev]            # where it may re-run; a protected one is a validation error
  pipelines: ["*"]
  retry_infra: {max_attempts: 2, backoff_seconds: [60, 300]}
  wait_for_upstream: {max_wait_minutes: 60}
  rerun_stale: false             # re-run nodes whose code changed since their last success
  catch_up: false                # run a pipeline late for its SLA
  max_actions_per_day: 10
  propose: {explain: true, fix_draft: true, remote: false}   # L2; unasked, only a local model
alerts:
  - when: [sentinel]             # escalations and recoveries
    channels: [{type: slack, webhook_env: SLACK_WEBHOOK}]
```

It runs inside the server (`ducta server start`: each finished run at once, and a
pass every `SENTINEL_SCAN_MINUTES` minutes, default 1, when `DUCTA_WORKSPACE` is
set) or as `ducta ai sentinel watch` (`--once` for cron). One pass at a time per
project.

| Diagnosis | Runbook | Level |
|---|---|---|
| another run held the lock (exit 7) | `retry_later` | L1 |
| infrastructure a re-run cannot fix (credentials, a missing driver, disk) | `escalate` | L0 |
| infrastructure, outputs overwritten or merged | `retry` (with backoff, up to `max_attempts`) | L1 |
| infrastructure, an output appended | `escalate`: a re-run would duplicate rows | L0 |
| data, the pipeline reads another pipeline, nothing appended | `wait_upstream`, re-run when it succeeds | L1 |
| quality gate | `propose_quality` | L2 |
| code, configuration, other | `propose_fix`: explanation + fix draft, never applied | L2 |
| late for its SLA | `catch_up` if allowed, else `escalate` | L1/L0 |
| much slower than its p95 | `suggest_review` | L2 |

An L1 action happens only when the policy allows it at that moment (enabled, the
environment listed and not protected, the pipeline matching, not paused, budget
left); otherwise the incident is escalated with the reason. A re-run covers the
failed (or stale) nodes and every node downstream of them, and "appended" is
judged on all of those. A later successful run resolves the incident. Everything is in `.ducta/ai/sentinel/`
(`incidents/`, `audit.jsonl`).

```bash
ducta ai sentinel status --output-format json
ducta ai sentinel incidents --output-format json   # --status active|escalated|resolved…
ducta ai sentinel show INCIDENT_ID
ducta ai sentinel triage RUN_ID --output-format json   # no model, no action
ducta ai sentinel watch --once
ducta ai sentinel pause --reason "db maintenance"; ducta ai sentinel resume
ducta ai sentinel resolve INCIDENT_ID --note "fixed upstream"
```

Server API: `GET /api/projects/{id}/sentinel/status|incidents|incidents/{iid}`
(`sentinel.read`); `POST …/incidents/{iid}/resolve|ignore|retry` and
`POST …/sentinel/pause|resume` (`sentinel.manage`: operators, admins). A proposal
is an AI job, `{"kind": "sentinel_propose", "incident_id": …}` (`ai.use`). Architect
runs as AI jobs: `{"kind": "architect_plan", "request": …}` and
`{"kind": "architect_build", "draft_id": …}`.
