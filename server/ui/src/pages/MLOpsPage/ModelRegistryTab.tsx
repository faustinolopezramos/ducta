import { useState } from "react";
import { colors, styles } from "../../theme/tokens";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import { Select } from "../../components/ui/Select";
import { ActionButton } from "../../components/ui/ActionButton";
import { PermittedButton } from "../../components/ui/PermittedButton";
import { requiresPermission, usePermission } from "../../hooks/usePermission";
import { EmptyState } from "../../components/ui/EmptyState";
import { Link } from "react-router-dom";
import {
  useMlopsModels,
  useMlopsStatus,
  useMlopsModelVersions,
  useMlopsRunTable,
  useModelHistory,
  usePromoteModel,
  usePromotionCheck,
  useRunMlopsGc,
  useDeleteModelVersion,
  type GcResult,
  type ModelHistoryEntry,
  type ModelInfo,
  type ModelServedBy,
  type ModelVersion,
  type RunTableRow,
} from "../../api/mlopsApi";
import { CertificateState } from "./RunBits";
import { routes } from "../../utils/routes";
import "./MLOps.css";
import {
  IconBrain,
  IconChevronDown,
  IconChevronRight,
  IconArrowUp,
  IconTrash,
  IconRefresh,
} from "@tabler/icons-react";
import { STAGE_COLOR } from "./shared";
import { MlopsEmptyState } from "./MlopsDiagnosis";
import { formatDate } from "../../utils/formatDate";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { Badge } from "../../components/ui/Badge";
import { Panel } from "../../components/ui/Panel";
import { Skeleton } from "../../components/ui/Skeleton";

/** The main metric of a set: the policy's, else the first one recorded. */
function mainMetric(metrics: Record<string, number> | null | undefined, preferred?: string) {
  const entries = Object.entries(metrics ?? {});
  const hit = entries.find(([k]) => k === preferred) ?? entries[0];
  return hit ? `${hit[0]} ${Number(hit[1]).toFixed(4)}` : null;
}

/** "score › score" for the nodes that serve whatever is in Production. */
function productionServers(servedBy: ModelServedBy[]): string[] {
  return servedBy
    .filter((s) => s.version == null && (s.stage ?? "").toLowerCase() === "production")
    .map((s) => `${s.pipeline ? `${s.pipeline} › ` : ""}${s.node}`);
}

function PromoteModal({
  model,
  version,
  versionStage,
  env,
  pipeline,
  project,
  onClose,
}: {
  model: ModelInfo;
  version: number;
  /** The stage the version is in now. */
  versionStage?: string;
  env?: string;
  pipeline?: string;
  project?: string;
  onClose: () => void;
}) {
  const modelName = model.name;
  // A Staging version is usually promoted to Production; anything else to Staging.
  const [stage, setStage] = useState<"staging" | "production" | "archived">(
    (versionStage ?? "Staging") === "Staging" ? "production" : "staging"
  );
  const [force, setForce] = useState(false);
  const [reason, setReason] = useState("");
  const promote = usePromoteModel();
  const toProduction = stage === "production";
  const { data: check, isLoading: checking } = usePromotionCheck(
    modelName,
    toProduction ? version : 0,
    env,
    pipeline,
    project
  );
  const needsReason = force && reason.trim() === "";

  function handlePromote() {
    promote.mutate(
      {
        name: modelName,
        version,
        stage,
        force: toProduction && force,
        reason: reason.trim() || undefined,
        env,
        pipelineName: pipeline,
        project,
      },
      { onSuccess: onClose }
    );
  }

  const policy = check?.policy;
  const servers = productionServers(check?.served_by ?? model.served_by ?? []);
  const current = check?.production_version ?? model.production_version ?? null;

  return (
    <Modal title={`Promote ${modelName} v${version}`} onClose={onClose} width={460}>
      <label htmlFor="promote-stage-select" style={{ display: "block", marginBottom: 6, fontSize: "var(--text-sm)", color: colors.textMuted }}>
        Target stage
      </label>
      <div style={{ marginBottom: 12 }}>
        <Select
          id="promote-stage-select"
          size="sm"
          value={stage}
          onChange={(e) => setStage(e.target.value as typeof stage)}
        >
          <option value="staging">Staging</option>
          <option value="production">Production</option>
          <option value="archived">Archived</option>
        </Select>
      </div>

      {toProduction && (
        <div className="mlops-promote-check" aria-label="Promotion policy">
          {checking ? (
            <span>Checking the promotion policy…</span>
          ) : !policy ? (
            <span>No promotion policy in this project: any version can be promoted.</span>
          ) : policy.error ? (
            <span className="mlops-promote-check--bad">
              The promotion policy cannot be used: {policy.error}
            </span>
          ) : (
            <>
              <span>
                Policy: <strong>{policy.metric}</strong>{" "}
                {policy.compare_to === "baseline" ? "must beat the trivial baseline" : `must beat the version in Production`}
                {policy.min_delta ? ` by ${policy.min_delta}` : ""}
                {policy.higher_is_better === false ? " (lower is better)" : ""}
              </span>
              {check?.passes ? (
                <span className="mlops-promote-check--ok">✓ v{version} passes</span>
              ) : (
                <span className="mlops-promote-check--bad">✗ {check?.reason ?? "it would be refused"}</span>
              )}
            </>
          )}
          <span style={{ color: colors.textMuted }}>
            {servers.length > 0
              ? `${servers.join(", ")} will score with v${version} from ${servers.length === 1 ? "its" : "their"} next run`
              : "No node of this project serves this model's Production version"}
            {current != null && current !== version ? `; v${current} → Archived.` : "."}
          </span>
        </div>
      )}

      {toProduction && (
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: "var(--text-sm)",
            color: colors.textMuted,
            cursor: "pointer",
            margin: "12px 0 8px",
          }}
        >
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
          Force (bypass the promotion policy)
        </label>
      )}
      <label htmlFor="promote-reason" style={{ display: "block", marginBottom: 6, fontSize: "var(--text-sm)", color: colors.textMuted }}>
        Reason {force ? "(required: it goes in the audit log)" : "(optional, kept in the audit log)"}
      </label>
      <input
        id="promote-reason"
        className="input-field"
        style={{ width: "100%", marginBottom: 20 }}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        aria-required={force}
      />

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={handlePromote}
          disabled={promote.isPending || needsReason}
          title={needsReason ? "A forced promotion needs a reason" : undefined}
        >
          {promote.isPending ? "Promoting…" : "Promote"}
        </Button>
      </div>
    </Modal>
  );
}

function GcModal({
  env,
  pipeline,
  project,
  onClose,
}: {
  env?: string;
  pipeline?: string;
  project?: string;
  onClose: () => void;
}) {
  const [dryRun, setDryRun] = useState(true);
  const gc = useRunMlopsGc();
  const [result, setResult] = useState<GcResult | null>(null);

  function handleGc() {
    gc.mutate(
      { dry_run: dryRun, env, pipelineName: pipeline, project },
      {
        onSuccess: (data) => {
          setResult(data);
          if (!dryRun) onClose();
        },
      }
    );
  }

  return (
    <Modal title="Model Garbage Collection" onClose={onClose} width={420}>
      <p style={{ margin: "0 0 16px", fontSize: "var(--text-sm)", color: colors.textMuted }}>
        Remove old model versions that are no longer needed.
      </p>

      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: "var(--text-sm)",
          color: colors.textMuted,
          cursor: "pointer",
          marginBottom: 16,
        }}
      >
        <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
        Dry run (preview only, no deletion)
      </label>

      {result && (
        <div
          style={{
            background: colors.bg,
            border: `1px solid ${colors.border}`,
            borderRadius: 6,
            padding: 12,
            fontSize: "var(--text-xs)",
            fontFamily: "var(--font-mono)",
            marginBottom: 16,
            color: colors.text,
          }}
        >
          <div>Models processed: {result.models_processed}</div>
          <div>Versions removed: {result.versions_removed}</div>
          <div>
            Bytes freed: {result.bytes_freed > 0 ? `${(result.bytes_freed / 1024).toFixed(1)} KB` : "0"}
          </div>
          {(result.versions ?? []).length > 0 && (
            <ul aria-label="Versions removed" style={{ margin: "8px 0 0", paddingLeft: 18 }}>
              {(result.versions ?? []).map((v) => (
                <li key={`${v.name}/${v.version}`}>
                  {v.name} v{v.version}
                  {v.created_at ? ` · ${formatDate(v.created_at, { includeYear: true })}` : ""}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <p style={{ margin: "0 0 16px", fontSize: "var(--text-xs)", color: colors.textMuted }}>
        A run that used a removed version can no longer be reproduced.
      </p>

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
        <Button variant="primary" size="sm" onClick={handleGc} disabled={gc.isPending}>
          {gc.isPending ? "Running…" : dryRun ? "Preview" : "Run GC"}
        </Button>
      </div>
    </Modal>
  );
}

function DeleteVersionButton({
  modelName,
  version,
  stage,
  env,
  pipeline,
  project,
}: {
  modelName: string;
  version: number;
  stage: string;
  env?: string;
  pipeline?: string;
  project?: string;
}) {
  const del = useDeleteModelVersion();
  const canDelete = usePermission("model.delete");
  // The registry refuses to delete the version in Production: the confirm used to
  // ask for the version to be typed out, and then the request always failed.
  const inProduction = stage === "Production";
  const confirmSpec = {
    title: `Delete ${modelName} v${version}?`,
    description: "This cannot be undone, and a run that used it can no longer be reproduced.",
    tone: "danger" as const,
    confirmLabel: "Delete version",
  };

  return (
    <ActionButton
      variant="ghost"
      size="sm"
      leftIcon={<IconTrash size={13} />}
      disabled={!canDelete || inProduction}
      title={
        !canDelete
          ? requiresPermission("model.delete")
          : inProduction
            ? "In Production: archive it (promote another version) before deleting"
            : undefined
      }
      confirm={confirmSpec}
      onAction={() =>
        del.mutateAsync({ name: modelName, version, env, pipelineName: pipeline, project })
      }
      successMessage={`Deleted v${version}`}
      errorMessage="Could not delete this version"
    >
      Delete
    </ActionButton>
  );
}

/** `score › score @ production` — which project nodes score with this model. */
export function ServedBy({ servedBy }: { servedBy: ModelServedBy[] }) {
  if (servedBy.length === 0) {
    return (
      <div className="mlops-served-by" style={{ marginTop: 6, fontSize: "var(--text-xs)", color: colors.textMuted }}>
        Not served by any node of this project.
      </div>
    );
  }
  return (
    <div
      className="mlops-served-by"
      aria-label="Served by"
      style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", fontSize: "var(--text-xs)" }}
    >
      <span style={{ color: colors.textMuted }}>Served by</span>
      {servedBy.map((s) => (
        // Not a <Badge>: it upper-cases, and these are identifiers.
        <span
          key={`${s.pipeline}/${s.node}`}
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "var(--text-2xs)",
            padding: "1px 6px",
            borderRadius: 4,
            border: `1px solid ${colors.border}`,
            color: colors.text,
          }}
        >
          {s.pipeline ? `${s.pipeline} › ` : ""}
          {s.node}
          {s.version != null ? ` v${s.version}` : ` @ ${s.stage ?? "?"}`}
          {s.streaming ? " (stream)" : ""}
        </span>
      ))}
    </div>
  );
}

/** Column definitions for the per-model versions table. */
/** The run that trained a version, with its certificate when the run table has it. */
function TrainedBy({ runId, row, project }: { runId?: string | null; row?: RunTableRow; project?: string }) {
  if (!runId) return <span title="Registered outside a tracked run">—</span>;
  const short = runId.slice(0, 8);
  if (!row?.certificate_id) {
    return <span title={`Run ${runId}${row ? "" : " (not a run of the pipeline picked above)"}`}>{short}</span>;
  }
  return (
    <span className="mlops-nowrap" style={{ display: "inline-flex", gap: 6, alignItems: "baseline" }}>
      <span title={`Run ${runId}`}>{short}</span>
      <Link to={routes.certificate(project || ".", row.certificate_id)}>
        <CertificateState id={row.certificate_id} ok={row.certificate_ok} />
      </Link>
    </span>
  );
}

function versionColumns({
  modelName,
  onPromote,
  runs,
  env,
  pipeline,
  project,
}: {
  modelName: string;
  onPromote: (version: number, stage: string) => void;
  /** Run table rows by run id: which run trained each version. */
  runs: Map<string, RunTableRow>;
  env?: string;
  pipeline?: string;
  project?: string;
}): DataTableColumn<ModelVersion>[] {
  const stageOf = (v: ModelVersion) => v.stage ?? "Staging";

  return [
    {
      key: "version",
      header: "Version",
      sortable: true,
      sortValue: (v) => Number(v.version),
      mono: true,
      cell: (v) => `v${v.version}`,
    },
    {
      key: "stage",
      header: "Stage",
      sortable: true,
      sortValue: stageOf,
      cell: (v) => <Badge color={STAGE_COLOR[stageOf(v)] ?? "var(--text-muted)"}>{stageOf(v)}</Badge>,
    },
    {
      key: "created_at",
      header: "Created",
      sortable: true,
      cell: (v) => formatDate(v.created_at, { includeYear: true }),
    },
    {
      key: "metrics",
      header: "Metrics",
      mono: true,
      cell: (v) => {
        const top = Object.entries(v.metrics ?? {}).slice(0, 3);
        return top.length
          ? top.map(([k, val]) => `${k}: ${Number(val).toFixed(4)}`).join(" · ")
          : "—";
      },
    },
    {
      key: "features",
      header: "Features",
      mono: true,
      cell: (v) => {
        const features = v.features ?? [];
        if (features.length === 0) return "—";
        const text = features.join(", ");
        return <span title={text}>{text.length > 40 ? `${text.slice(0, 37)}…` : text}</span>;
      },
    },
    {
      key: "experiment_run_id",
      header: "Trained by",
      mono: true,
      cell: (v) => (
        <TrainedBy
          runId={v.experiment_run_id}
          row={v.experiment_run_id ? runs.get(v.experiment_run_id) : undefined}
          project={project}
        />
      ),
    },
    {
      key: "artifact_sha256",
      header: "Artifact",
      mono: true,
      cell: (v) =>
        v.artifact_sha256 ? (
          <span title={`${v.artifact_sha256}\nServing refuses a copy that no longer matches this hash.`}>
            {v.artifact_sha256.replace("sha256:", "").slice(0, 12)}
          </span>
        ) : (
          <span title="Registered before Ducta recorded artifact hashes">—</span>
        ),
    },
    {
      key: "actions",
      header: "",
      headerLabel: "Version actions",
      align: "right",
      cell: (v) => (
        <div className="mlops-row-actions">
          <PermittedButton
            permission="model.promote"
            variant="ghost"
            size="sm"
            onClick={() => onPromote(v.version, stageOf(v))}
            title={`Promote v${v.version}`}
          >
            <IconArrowUp size={13} />
            Promote
          </PermittedButton>
          <DeleteVersionButton
            modelName={modelName}
            version={v.version}
            stage={stageOf(v)}
            env={env}
            pipeline={pipeline}
            project={project}
          />
        </div>
      ),
    },
  ];
}

const EVENT_LABEL: Record<string, string> = {
  REGISTER: "registered",
  PROMOTE: "promoted",
  PROMOTE_REFUSED: "promotion refused",
  DEMOTE: "archived",
  DELETE: "deleted",
};

function historyDetail(entry: ModelHistoryEntry): string {
  const d = entry.details ?? {};
  const parts: string[] = [];
  if (entry.event === "PROMOTE" && d.new_stage) parts.push(`→ ${String(d.new_stage)}`);
  if (Array.isArray(d.demoted_versions) && d.demoted_versions.length) {
    parts.push(`archived ${d.demoted_versions.map((v) => `v${v}`).join(", ")}`);
  }
  if (d.gate_bypassed) parts.push("policy bypassed (force)");
  if (entry.event === "PROMOTE_REFUSED" && d.refusal) parts.push(String(d.refusal));
  if (entry.event === "DELETE" && d.stage) parts.push(`was ${String(d.stage)}`);
  return parts.join(" · ");
}

/** Who registered, promoted, refused or deleted which version, newest first. */
function ModelHistory({ name, env, pipeline, project }: { name: string; env?: string; pipeline?: string; project?: string }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useModelHistory(open ? name : "", env, pipeline, project);
  return (
    <details className="mlops-history" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>History</summary>
      {isLoading && <Skeleton variant="text" width="60%" />}
      {open && !isLoading && (data ?? []).length === 0 && <p className="mlops-history__empty">No audit entries.</p>}
      {(data ?? []).length > 0 && (
        <ol aria-label={`History of ${name}`}>
          {(data ?? []).map((e, i) => (
            <li key={`${e.timestamp}-${i}`} className={e.event === "PROMOTE_REFUSED" ? "mlops-history__refused" : undefined}>
              <span className="mlops-history__when">{formatDate(e.timestamp, { includeYear: true })}</span>{" "}
              <strong>{e.user}</strong> {EVENT_LABEL[e.event] ?? e.event.toLowerCase()} v{e.version}
              {historyDetail(e) ? ` · ${historyDetail(e)}` : ""}
              {e.reason && e.reason !== "No reason provided" ? ` — “${e.reason}”` : ""}
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}

/** The stage a model is filed under: Production when any version serves from it. */
export function groupStage(model: ModelInfo): string {
  if (model.production_version != null) return "Production";
  return model.stage ?? "Staging";
}

function ModelCard({
  model,
  policyMetric,
  env,
  pipeline,
  project,
}: {
  model: ModelInfo;
  policyMetric?: string;
  env?: string;
  pipeline?: string;
  project?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [promoteTarget, setPromoteTarget] = useState<{ version: number; stage?: string } | null>(null);
  const { data: versions, isLoading } = useMlopsModelVersions(
    expanded ? model.name : "",
    env,
    pipeline,
    project
  );
  const { data: runTable } = useMlopsRunTable(env, pipeline, project);
  const runs = new Map((runTable?.rows ?? []).map((r) => [r.run_id, r]));
  const production = model.production_version ?? null;
  const latestIsProduction = production === model.latest_version;
  const productionMetric = mainMetric(model.production_metrics, policyMetric);

  return (
    <>
      <Panel>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse versions" : "Expand versions"}
            style={{ ...styles.resetButton, width: "auto", display: "flex", alignItems: "center" }}
          >
            {expanded ? (
              <IconChevronDown size={16} color={colors.textMuted} />
            ) : (
              <IconChevronRight size={16} color={colors.textMuted} />
            )}
          </button>
          <span style={{ fontWeight: 600, color: colors.text, flex: 1 }}>{model.name}</span>
          <span style={{ fontSize: "var(--text-xs)", color: colors.textMuted }}>{model.framework ?? "—"}</span>
          {!latestIsProduction && (
            <PermittedButton
              permission="model.promote"
              variant="ghost"
              size="sm"
              onClick={() => setPromoteTarget({ version: model.latest_version, stage: model.stage })}
              title={`Promote the latest version, v${model.latest_version}`}
            >
              <IconArrowUp size={14} />
              Promote v{model.latest_version}
            </PermittedButton>
          )}
        </div>

        <div className="mlops-model-lines">
          {production != null ? (
            <div>
              In production: <strong className="mlops-mono">v{production}</strong>
              {productionMetric ? <span className="mlops-mono"> · {productionMetric}</span> : null}
            </div>
          ) : (
            <div>No version in Production.</div>
          )}
          {!latestIsProduction && (
            <div>
              Latest: <span className="mlops-mono">v{model.latest_version}</span>{" "}
              <Badge color={STAGE_COLOR[model.stage ?? "Staging"] ?? "var(--text-muted)"}>{model.stage ?? "Staging"}</Badge>{" "}
              <span style={{ color: colors.textMuted }}>· {formatDate(model.created_at, { includeYear: true })}</span>
              {model.latest_refusal?.reason && (
                <span className="mlops-refusal"> — refused by the promotion policy: {model.latest_refusal.reason}</span>
              )}
            </div>
          )}
        </div>

        <ServedBy servedBy={model.served_by ?? []} />

        {expanded && (
          <div style={{ marginTop: "var(--space-3)" }}>
            <DataTable<ModelVersion>
              density="compact"
              columns={versionColumns({
                modelName: model.name,
                onPromote: (version, stage) => setPromoteTarget({ version, stage }),
                runs,
                env,
                pipeline,
                project,
              })}
              rows={versions ?? []}
              rowKey={(v) => String(v.version)}
              loading={isLoading}
              loadingRows={3}
              empty={<span>No versions found.</span>}
            />
            <ModelHistory name={model.name} env={env} pipeline={pipeline} project={project} />
          </div>
        )}
      </Panel>

      {promoteTarget != null && (
        <PromoteModal
          model={model}
          version={promoteTarget.version}
          versionStage={promoteTarget.stage}
          env={env}
          pipeline={pipeline}
          project={project}
          onClose={() => setPromoteTarget(null)}
        />
      )}
    </>
  );
}

export function ModelRegistryTab({
  env,
  pipeline,
  project,
}: {
  env?: string;
  pipeline?: string;
  project?: string;
}) {
  const { data, isLoading, isError, refetch } = useMlopsModels(env, pipeline, project);
  const { data: status } = useMlopsStatus(env, pipeline, project);
  const [showGc, setShowGc] = useState(false);
  const models = data ?? [];

  const byStage: Record<string, ModelInfo[]> = {
    Production: [],
    Staging: [],
    Archived: [],
  };
  // Filed by what serves: the latest version's stage put a model whose refused
  // retrain sits in Staging under Staging, with no sign of v1 still in Production.
  for (const m of models) {
    const s = groupStage(m);
    if (!byStage[s]) byStage[s] = [];
    byStage[s].push(m);
  }

  if (!pipeline) {
    return (
      <EmptyState
        icon={IconBrain}
        title="Select a pipeline to view registered models"
        description="Pick an ML pipeline above to see its registered models and versions."
        size="lg"
      />
    );
  }

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        {/* The registry belongs to the project: every ML pipeline registers into
            the same one, and a model does not record which pipeline trained it,
            so the pipeline picked above does not narrow this list. */}
        <span style={{ fontSize: "var(--text-sm)", color: colors.textMuted }}>
          {models.length} model{models.length !== 1 ? "s" : ""} in this project's registry
        </span>
        <div style={{ display: "flex", gap: 8 }}>
          <Button variant="ghost" size="sm" onClick={() => refetch()} leftIcon={<IconRefresh size={14} />}>
            Refresh
          </Button>
          <PermittedButton
            permission="model.delete"
            variant="ghost"
            size="sm"
            onClick={() => setShowGc(true)}
            leftIcon={<IconTrash size={14} />}
            title="Delete old, unused model versions to free disk space"
          >
            Run GC
          </PermittedButton>
        </div>
      </div>

      {isLoading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Skeleton variant="block" height="80px" />
          <Skeleton variant="block" height="80px" />
          <Skeleton variant="block" height="80px" />
        </div>
      )}
      {isError && (
        <div style={{ color: "var(--danger)", fontSize: "var(--text-sm)" }}>
          Failed to load model registry. Check that MLOps is configured in the workspace.
        </div>
      )}
      {!isLoading && !isError && models.length === 0 && (
        <MlopsEmptyState status={status} env={env} what="models" icon={IconBrain} />
      )}

      {(["Production", "Staging", "Archived"] as const).map((stage) =>
        byStage[stage]?.length > 0 ? (
          <div key={stage} style={{ marginBottom: 20 }}>
            <h3
              style={{
                fontSize: "var(--text-xs)",
                fontWeight: 600,
                color: STAGE_COLOR[stage] ?? colors.textMuted,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                margin: "0 0 8px",
              }}
            >
              {stage} ({byStage[stage].length})
            </h3>
            {byStage[stage].map((m) => (
              <ModelCard
                key={m.name}
                model={m}
                policyMetric={status?.promotion_policy?.metric}
                env={env}
                pipeline={pipeline}
                project={project}
              />
            ))}
          </div>
        ) : null
      )}

      {showGc && (
        <GcModal env={env} pipeline={pipeline} project={project} onClose={() => setShowGc(false)} />
      )}
    </div>
  );
}
