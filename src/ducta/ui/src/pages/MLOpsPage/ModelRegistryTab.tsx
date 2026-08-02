import { useState } from "react";
import { colors } from "../../theme/tokens";
import { Button } from "../../components/ui/Button";
import { ActionButton } from "../../components/ui/ActionButton";
import { EmptyState } from "../../components/ui/EmptyState";
import {
  useMlopsModels,
  useMlopsModelVersions,
  usePromoteModel,
  useRunMlopsGc,
  useDeleteModelVersion,
  type ModelInfo,
  type ModelVersion,
} from "../../api/mlopsApi";
import {
  IconBrain,
  IconChevronDown,
  IconChevronRight,
  IconArrowUp,
  IconTrash,
  IconRefresh,
  IconAlertTriangle,
} from "@tabler/icons-react";
import { card, STAGE_COLOR, StageBadge, formatDate } from "./shared";

function PromoteModal({
  modelName,
  version,
  onClose,
}: {
  modelName: string;
  version: number;
  onClose: () => void;
}) {
  const [stage, setStage] = useState<"staging" | "production" | "archived">("staging");
  const [force, setForce] = useState(false);
  const promote = usePromoteModel();

  function handlePromote() {
    promote.mutate({ name: modelName, version, stage, force }, { onSuccess: onClose });
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
          borderRadius: 10,
          padding: 24,
          width: 360,
          maxWidth: "90vw",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: "0 0 16px", color: colors.text, fontSize: 15 }}>
          Promote {modelName} v{version}
        </h3>

        <label style={{ display: "block", marginBottom: 12, fontSize: 13, color: colors.textMuted }}>
          Target stage
          <select
            value={stage}
            onChange={(e) => setStage(e.target.value as typeof stage)}
            style={{
              display: "block",
              marginTop: 4,
              width: "100%",
              padding: "6px 10px",
              borderRadius: 6,
              border: `1px solid ${colors.border}`,
              background: colors.bg,
              color: colors.text,
              fontSize: 13,
            }}
          >
            <option value="staging">Staging</option>
            <option value="production">Production</option>
            <option value="archived">Archived</option>
          </select>
        </label>

        {stage === "production" && (
          <div
            style={{
              margin: "12px 0",
              padding: "8px 12px",
              borderRadius: 6,
              background: "color-mix(in srgb, var(--warning) 12%, transparent)",
              border: "1px solid var(--warning)",
              color: "var(--warning)",
              fontSize: 12,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <IconAlertTriangle size={16} style={{ flexShrink: 0 }} />
            Promoting to Production will make this version live for all pipeline runs.
          </div>
        )}

        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 13,
            color: colors.textMuted,
            cursor: "pointer",
            marginBottom: 20,
          }}
        >
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
          Force (bypass promotion policy)
        </label>

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" onClick={handlePromote} disabled={promote.isPending}>
            {promote.isPending ? "Promoting…" : "Promote"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function GcModal({ onClose }: { onClose: () => void }) {
  const [dryRun, setDryRun] = useState(true);
  const gc = useRunMlopsGc();
  const [result, setResult] = useState<Record<string, any> | null>(null);

  function handleGc() {
    gc.mutate(
      { dry_run: dryRun },
      {
        onSuccess: (data) => {
          setResult(data);
          if (!dryRun) onClose();
        },
      }
    );
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
          borderRadius: 10,
          padding: 24,
          width: 380,
          maxWidth: "90vw",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: "0 0 8px", color: colors.text, fontSize: 15 }}>
          Model Garbage Collection
        </h3>
        <p style={{ margin: "0 0 16px", fontSize: 13, color: colors.textMuted }}>
          Remove old model versions that are no longer needed.
        </p>

        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 13,
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
              fontSize: 12,
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
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
          <Button variant="primary" size="sm" onClick={handleGc} disabled={gc.isPending}>
            {gc.isPending ? "Running…" : dryRun ? "Preview" : "Run GC"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function DeleteVersionButton({
  modelName,
  version,
  stage,
}: {
  modelName: string;
  version: number;
  stage: string;
}) {
  const del = useDeleteModelVersion();
  const confirmMsg =
    stage === "Production"
      ? `'${modelName}' v${version} is in PRODUCTION. Delete anyway? This cannot be undone.`
      : `Delete '${modelName}' v${version}? This cannot be undone.`;

  return (
    <ActionButton
      variant="ghost"
      size="sm"
      leftIcon={<IconTrash size={13} />}
      confirm={confirmMsg}
      onAction={() => del.mutateAsync({ name: modelName, version })}
      successMessage={`Deleted v${version}`}
      errorMessage="Could not delete this version"
    >
      Delete
    </ActionButton>
  );
}

function ModelCard({ model }: { model: ModelInfo }) {
  const [expanded, setExpanded] = useState(false);
  const [promoteTarget, setPromoteTarget] = useState<number | null>(null);
  const { data: versions, isLoading } = useMlopsModelVersions(expanded ? model.name : "");

  return (
    <>
      <div style={card}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <span
            onClick={() => setExpanded((v) => !v)}
            style={{ cursor: "pointer", display: "flex", alignItems: "center" }}
          >
            {expanded ? (
              <IconChevronDown size={16} color={colors.textMuted} />
            ) : (
              <IconChevronRight size={16} color={colors.textMuted} />
            )}
          </span>
          <span style={{ fontWeight: 600, color: colors.text, flex: 1 }}>{model.name}</span>
          <StageBadge stage={model.stage ?? "Staging"} />
          <span style={{ fontSize: 12, color: colors.textMuted, fontFamily: "var(--font-mono)" }}>
            v{model.latest_version}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPromoteTarget(model.latest_version)}
            title="Promote latest version"
          >
            <IconArrowUp size={14} />
            Promote
          </Button>
        </div>

        <div style={{ display: "flex", gap: 16, fontSize: 12, color: colors.textMuted }}>
          <span>Framework: {model.framework ?? "—"}</span>
          <span>Created: {formatDate(model.created_at)}</span>
        </div>

        {expanded && (
          <div style={{ marginTop: 12 }}>
            {isLoading ? (
              <div style={{ fontSize: 13, color: colors.textMuted }}>Loading versions…</div>
            ) : !versions?.length ? (
              <div style={{ fontSize: 13, color: colors.textMuted }}>No versions found.</div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ color: colors.textMuted }}>
                    {["Version", "Stage", "Created", "Metrics", ""].map((h) => (
                      <th key={h} style={{ textAlign: "left", padding: "4px 8px", fontWeight: 500 }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {versions.map((v: ModelVersion) => {
                    const meta = v.metadata ?? {};
                    const metrics = meta.metrics ?? {};
                    const topMetrics = Object.entries(metrics).slice(0, 3);
                    const stage = meta.stage ?? "Staging";
                    return (
                      <tr key={v.version} style={{ borderTop: `1px solid ${colors.border}` }}>
                        <td
                          style={{ padding: "6px 8px", color: colors.text, fontFamily: "var(--font-mono)" }}
                        >
                          v{v.version}
                        </td>
                        <td style={{ padding: "6px 8px" }}>
                          <StageBadge stage={stage} />
                        </td>
                        <td style={{ padding: "6px 8px", color: colors.textMuted }}>
                          {formatDate(v.created_at)}
                        </td>
                        <td
                          style={{
                            padding: "6px 8px",
                            color: colors.textMuted,
                            fontFamily: "var(--font-mono)",
                            fontSize: 11,
                          }}
                        >
                          {topMetrics.length
                            ? topMetrics.map(([k, val]) => `${k}: ${Number(val).toFixed(4)}`).join(" · ")
                            : "—"}
                        </td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>
                          <div style={{ display: "flex", gap: 4, justifyContent: "flex-end" }}>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setPromoteTarget(v.version)}
                              title={`Promote v${v.version}`}
                            >
                              <IconArrowUp size={13} />
                              Promote
                            </Button>
                            <DeleteVersionButton modelName={model.name} version={v.version} stage={stage} />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      {promoteTarget != null && (
        <PromoteModal
          modelName={model.name}
          version={promoteTarget}
          onClose={() => setPromoteTarget(null)}
        />
      )}
    </>
  );
}

export function ModelRegistryTab() {
  const { data, isLoading, isError, refetch } = useMlopsModels();
  const [showGc, setShowGc] = useState(false);
  const models = data ?? [];

  const byStage: Record<string, ModelInfo[]> = {
    Production: [],
    Staging: [],
    Archived: [],
  };
  for (const m of models) {
    const s = m.stage ?? "Staging";
    if (!byStage[s]) byStage[s] = [];
    byStage[s].push(m);
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
        <span style={{ fontSize: 13, color: colors.textMuted }}>
          {models.length} model{models.length !== 1 ? "s" : ""}
        </span>
        <div style={{ display: "flex", gap: 8 }}>
          <Button variant="ghost" size="sm" onClick={() => refetch()}>
            <IconRefresh size={14} />
            Refresh
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setShowGc(true)}>
            <IconTrash size={14} />
            Run GC
          </Button>
        </div>
      </div>

      {isLoading && <div style={{ color: colors.textMuted, fontSize: 13 }}>Loading model registry…</div>}
      {isError && (
        <div style={{ color: "var(--danger)", fontSize: 13 }}>
          Failed to load model registry. Check that MLOps is configured in the workspace.
        </div>
      )}
      {!isLoading && !isError && models.length === 0 && (
        <EmptyState
          icon={IconBrain}
          title="No models registered"
          description="Register a model with persist_model: true in an ML pipeline node."
        />
      )}

      {(["Production", "Staging", "Archived"] as const).map((stage) =>
        byStage[stage]?.length > 0 ? (
          <div key={stage} style={{ marginBottom: 20 }}>
            <h3
              style={{
                fontSize: 12,
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
              <ModelCard key={m.name} model={m} />
            ))}
          </div>
        ) : null
      )}

      {showGc && <GcModal onClose={() => setShowGc(false)} />}
    </div>
  );
}
