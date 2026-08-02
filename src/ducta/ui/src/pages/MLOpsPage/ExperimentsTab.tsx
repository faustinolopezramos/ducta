import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { colors } from "../../theme/tokens";
import { Button } from "../../components/ui/Button";
import { ActionButton } from "../../components/ui/ActionButton";
import { EmptyState } from "../../components/ui/EmptyState";
import {
  useMlopsExperiments,
  useMlopsExperiment,
  useCloseMlopsRun,
  useDeleteMlopsRun,
  lastMetricValues,
  type ExperimentSummary,
  type ExperimentRun,
} from "../../api/mlopsApi";
import { useExecutePipeline } from "../../api/mutations";
import { RunDetailPanel } from "../../components/MLOps/RunDetailPanel";
import { RunCompareModal } from "../../components/MLOps/RunCompareModal";
import {
  IconFlask,
  IconChevronDown,
  IconChevronRight,
  IconTrash,
  IconRefresh,
  IconPlayerPlay,
  IconAlertTriangle,
  IconArrowsDiff,
} from "@tabler/icons-react";
import { card, formatDate, findProjectForPipeline } from "./shared";

function RunActionsCell({ experimentId, run }: { experimentId: string; run: ExperimentRun }) {
  const navigate = useNavigate();
  const executePipeline = useExecutePipeline();
  const closeRun = useCloseMlopsRun();
  const deleteRun = useDeleteMlopsRun();

  const handleRerun = async () => {
    const pipelineName = run.tags?.pipeline_name;
    if (!pipelineName) {
      throw new Error("This run has no recorded pipeline name — it predates rerun support");
    }
    // Prefer the project_id tag (recorded by newer runs); fall back to scanning.
    const projectId = run.tags?.project_id ?? (await findProjectForPipeline(pipelineName));
    if (!projectId) {
      throw new Error(`No project contains a pipeline named '${pipelineName}'`);
    }
    await executePipeline.mutateAsync({ projectId, pipelineName });
    navigate(`/project/${projectId}/pipeline/${pipelineName}`);
  };

  return (
    <div style={{ display: "flex", gap: 4, justifyContent: "flex-end" }}>
      <ActionButton
        variant="ghost"
        size="sm"
        leftIcon={<IconPlayerPlay size={13} />}
        onAction={handleRerun}
        successMessage="Pipeline re-run started"
        errorMessage="Could not re-run this pipeline"
      >
        Rerun
      </ActionButton>
      {run.status === "RUNNING" && (
        <ActionButton
          variant="ghost"
          size="sm"
          leftIcon={<IconAlertTriangle size={13} />}
          confirm={`Mark run '${run.name ?? run.run_id}' as failed? Use this only if it's stuck (crashed process).`}
          onAction={() =>
            closeRun.mutateAsync({ experimentId, runId: run.run_id, status: "FAILED" })
          }
          successMessage="Run marked as failed"
          errorMessage="Could not close run"
        >
          Mark failed
        </ActionButton>
      )}
      <ActionButton
        variant="ghost"
        size="sm"
        leftIcon={<IconTrash size={13} />}
        confirm={`Delete run '${run.name ?? run.run_id}'? This cannot be undone.`}
        onAction={() => deleteRun.mutateAsync({ experimentId, runId: run.run_id })}
        successMessage="Run deleted"
        errorMessage="Could not delete run"
      >
        Delete
      </ActionButton>
    </div>
  );
}

/** Compact "metric: value" preview for a run row (top 2 metrics). */
function runMetricsPreview(run: ExperimentRun): string {
  const entries = Object.entries(lastMetricValues(run)).slice(0, 2);
  if (entries.length === 0) return "—";
  return entries.map(([k, v]) => `${k}: ${v.toFixed(4)}`).join(" · ");
}

function ExperimentRow({
  exp,
  compareSelection,
  onToggleCompare,
  onOpenRun,
}: {
  exp: ExperimentSummary;
  compareSelection: Map<string, ExperimentRun>;
  onToggleCompare: (run: ExperimentRun) => void;
  onOpenRun: (run: ExperimentRun) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data: detail, isLoading } = useMlopsExperiment(expanded ? exp.experiment_id : "");

  return (
    <div style={card}>
      <div
        onClick={() => setExpanded((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          cursor: "pointer",
          userSelect: "none",
        }}
      >
        {expanded ? (
          <IconChevronDown size={16} color={colors.textMuted} />
        ) : (
          <IconChevronRight size={16} color={colors.textMuted} />
        )}
        <span style={{ fontWeight: 600, color: colors.text, flex: 1 }}>
          {exp.name ?? exp.experiment_id}
        </span>
        <span style={{ fontSize: 12, color: colors.textMuted }}>{formatDate(exp.created_at)}</span>
        <span style={{ fontSize: 11, color: colors.textMuted, fontFamily: "var(--font-mono)" }}>
          {String(exp.experiment_id ?? "").slice(0, 8)}
        </span>
      </div>

      {expanded && (
        <div style={{ marginTop: 12 }}>
          {isLoading ? (
            <div style={{ color: colors.textMuted, fontSize: 13 }}>Loading runs…</div>
          ) : !detail?.runs?.length ? (
            <div style={{ color: colors.textMuted, fontSize: 13 }}>No runs found.</div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ color: colors.textMuted }}>
                  {["", "Run", "Status", "Created", "Duration", "Metrics", ""].map((h, i) => (
                    <th key={i} style={{ textAlign: "left", padding: "4px 8px", fontWeight: 500 }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {detail.runs.map((run) => (
                  <tr key={run.run_id} style={{ borderTop: `1px solid ${colors.border}` }}>
                    <td style={{ padding: "6px 4px 6px 8px", width: 24 }}>
                      <input
                        type="checkbox"
                        checked={compareSelection.has(run.run_id)}
                        onChange={() => onToggleCompare(run)}
                        aria-label={`Select run ${run.name ?? run.run_id} for comparison`}
                        title="Select for comparison"
                        style={{ cursor: "pointer" }}
                      />
                    </td>
                    <td style={{ padding: "6px 8px" }}>
                      <button
                        onClick={() => onOpenRun(run)}
                        title="Open run details"
                        style={{
                          background: "none",
                          border: "none",
                          padding: 0,
                          cursor: "pointer",
                          color: colors.accent,
                          fontSize: 12,
                          fontFamily: "var(--font-mono)",
                        }}
                      >
                        {run.name ?? String(run.run_id ?? "").slice(0, 8)}
                      </button>
                    </td>
                    <td style={{ padding: "6px 8px" }}>
                      <span
                        style={{
                          color:
                            run.status === "COMPLETED"
                              ? "var(--success)"
                              : run.status === "FAILED"
                                ? "var(--danger)"
                                : "var(--warning)",
                          fontWeight: 600,
                          fontSize: 11,
                        }}
                      >
                        {run.status}
                      </span>
                    </td>
                    <td style={{ padding: "6px 8px", color: colors.textMuted }}>
                      {formatDate(run.created_at)}
                    </td>
                    <td style={{ padding: "6px 8px", color: colors.textMuted }}>
                      {run.duration_seconds != null
                        ? `${Number(run.duration_seconds).toFixed(1)}s`
                        : "—"}
                    </td>
                    <td
                      style={{
                        padding: "6px 8px",
                        color: colors.textMuted,
                        fontFamily: "var(--font-mono)",
                        fontSize: 11,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        maxWidth: 200,
                      }}
                    >
                      {runMetricsPreview(run)}
                    </td>
                    <td style={{ padding: "6px 8px" }}>
                      <RunActionsCell experimentId={exp.experiment_id} run={run} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

export function ExperimentsTab() {
  const { data, isLoading, isError, refetch } = useMlopsExperiments();
  const experiments = data ?? [];
  const [compareSelection, setCompareSelection] = useState<Map<string, ExperimentRun>>(new Map());
  const [openRun, setOpenRun] = useState<ExperimentRun | null>(null);
  const [showCompare, setShowCompare] = useState(false);

  const toggleCompare = (run: ExperimentRun) =>
    setCompareSelection((cur) => {
      const next = new Map(cur);
      if (next.has(run.run_id)) next.delete(run.run_id);
      else next.set(run.run_id, run);
      return next;
    });

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
          {experiments.length} experiment{experiments.length !== 1 ? "s" : ""}
          {compareSelection.size > 0 && ` · ${compareSelection.size} run(s) selected`}
        </span>
        <div style={{ display: "flex", gap: 8 }}>
          {compareSelection.size >= 2 && (
            <Button variant="primary" size="sm" onClick={() => setShowCompare(true)}>
              <IconArrowsDiff size={14} />
              Compare {compareSelection.size} runs
            </Button>
          )}
          {compareSelection.size > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setCompareSelection(new Map())}>
              Clear selection
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => refetch()}>
            <IconRefresh size={14} />
            Refresh
          </Button>
        </div>
      </div>

      {isLoading && <div style={{ color: colors.textMuted, fontSize: 13 }}>Loading experiments…</div>}
      {isError && (
        <div style={{ color: "var(--danger)", fontSize: 13 }}>
          Failed to load experiments. Check that MLOps is configured in the workspace.
        </div>
      )}
      {!isLoading && !isError && experiments.length === 0 && (
        <EmptyState
          icon={IconFlask}
          title="No experiments yet"
          description="Run a pipeline with mlops_enabled: true to start tracking experiments."
        />
      )}
      {experiments.map((exp) => (
        <ExperimentRow
          key={exp.experiment_id}
          exp={exp}
          compareSelection={compareSelection}
          onToggleCompare={toggleCompare}
          onOpenRun={setOpenRun}
        />
      ))}

      {openRun && <RunDetailPanel run={openRun} onClose={() => setOpenRun(null)} />}
      {showCompare && (
        <RunCompareModal runs={[...compareSelection.values()]} onClose={() => setShowCompare(false)} />
      )}
    </div>
  );
}
