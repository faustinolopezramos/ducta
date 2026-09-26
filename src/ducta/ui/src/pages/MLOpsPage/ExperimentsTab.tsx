import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { colors, styles } from "../../theme/tokens";
import { Button } from "../../components/ui/Button";
import { ActionButton } from "../../components/ui/ActionButton";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { EmptyState } from "../../components/ui/EmptyState";
import { Panel } from "../../components/ui/Panel";
import { Skeleton } from "../../components/ui/Skeleton";
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
import { findProjectForPipeline } from "./shared";
import { formatDate } from "../../utils/formatDate";

function RunActionsCell({
  experimentId,
  run,
  env,
  pipeline,
  project,
}: {
  experimentId: string;
  run: ExperimentRun;
  env?: string;
  pipeline?: string;
  project?: string;
}) {
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
          confirm={{
            title: `Mark ${run.name ?? run.run_id} as failed?`,
            description:
              "Use this only when the run is stuck because its process crashed. It edits the recorded outcome; it does not stop anything.",
            confirmLabel: "Mark failed",
          }}
          onAction={() =>
            closeRun.mutateAsync({
              experimentId,
              runId: run.run_id,
              status: "FAILED",
              env,
              pipelineName: pipeline,
              project,
            })
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
        confirm={{
          title: `Delete run ${run.name ?? run.run_id}?`,
          description: "Its metrics, parameters and artifacts go with it. This cannot be undone.",
          tone: "danger",
          confirmLabel: "Delete run",
        }}
        onAction={() =>
          deleteRun.mutateAsync({
            experimentId,
            runId: run.run_id,
            env,
            pipelineName: pipeline,
            project,
          })
        }
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

/**
 * Column definitions for the per-experiment runs table.
 *
 * Compare-selection stays a plain column rather than DataTable's `selection`
 * prop: that one models a set of row ids, and this screen needs the whole run
 * object to hand to the compare modal.
 */
function runColumns({
  experimentId,
  compareSelection,
  onToggleCompare,
  onOpenRun,
  env,
  pipeline,
  project,
}: {
  experimentId: string;
  compareSelection: Map<string, ExperimentRun>;
  onToggleCompare: (run: ExperimentRun) => void;
  onOpenRun: (run: ExperimentRun) => void;
  env?: string;
  pipeline?: string;
  project?: string;
}): DataTableColumn<ExperimentRun>[] {
  return [
    {
      key: "compare",
      header: "",
      headerLabel: "Select for comparison",
      width: "32px",
      cell: (run) => (
        <input
          type="checkbox"
          checked={compareSelection.has(run.run_id)}
          onChange={() => onToggleCompare(run)}
          aria-label={`Select run ${run.name ?? run.run_id} for comparison`}
          title="Select for comparison"
          style={{ cursor: "pointer" }}
        />
      ),
    },
    {
      key: "name",
      header: "Run",
      sortable: true,
      sortValue: (run) => run.name ?? String(run.run_id ?? ""),
      cell: (run) => (
        <button
          onClick={() => onOpenRun(run)}
          title="Open run details"
          className="mlops-run-link"
        >
          {run.name ?? String(run.run_id ?? "").slice(0, 8)}
        </button>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      cell: (run) => <RunStatusLabel status={run.status} />,
    },
    {
      key: "created_at",
      header: "Created",
      sortable: true,
      cell: (run) => formatDate(run.created_at, { includeYear: true }),
    },
    {
      key: "duration_seconds",
      header: "Duration",
      sortable: true,
      align: "right",
      mono: true,
      cell: (run) =>
        run.duration_seconds != null ? `${Number(run.duration_seconds).toFixed(1)}s` : "—",
    },
    {
      key: "metrics",
      header: "Metrics",
      mono: true,
      width: "200px",
      cell: (run) => <span className="mlops-metrics-preview">{runMetricsPreview(run)}</span>,
    },
    {
      key: "actions",
      header: "",
      headerLabel: "Run actions",
      align: "right",
      cell: (run) => (
        <RunActionsCell experimentId={experimentId} run={run} env={env} pipeline={pipeline} project={project} />
      ),
    },
  ];
}

/** Status word, coloured by outcome. Colour is never the only signal — the
 *  word itself carries the meaning (WCAG 1.4.1). */
function RunStatusLabel({ status }: Readonly<{ status?: string }>) {
  const tone =
    status === "COMPLETED" ? "success" : status === "FAILED" ? "danger" : "warning";
  return <span className={`mlops-run-status mlops-run-status--${tone}`}>{status}</span>;
}

function ExperimentRow({
  exp,
  compareSelection,
  onToggleCompare,
  onOpenRun,
  env,
  pipeline,
  project,
}: {
  exp: ExperimentSummary;
  compareSelection: Map<string, ExperimentRun>;
  onToggleCompare: (run: ExperimentRun) => void;
  onOpenRun: (run: ExperimentRun) => void;
  env?: string;
  pipeline?: string;
  project?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data: detail, isLoading } = useMlopsExperiment(
    expanded ? exp.experiment_id : "",
    env,
    pipeline,
    project
  );

  return (
    <Panel>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        style={{
          ...styles.resetButton,
          display: "flex",
          alignItems: "center",
          gap: 10,
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
        <span style={{ fontSize: 12, color: colors.textMuted }}>{formatDate(exp.created_at, { includeYear: true })}</span>
        <span style={{ fontSize: 11, color: colors.textMuted, fontFamily: "var(--font-mono)" }}>
          {String(exp.experiment_id ?? "").slice(0, 8)}
        </span>
      </button>

      {expanded && (
        <div style={{ marginTop: "var(--space-3)" }}>
          <DataTable<ExperimentRun>
            density="compact"
            columns={runColumns({
              experimentId: exp.experiment_id,
              compareSelection,
              onToggleCompare,
              onOpenRun,
              env,
              pipeline,
              project,
            })}
            rows={detail?.runs ?? []}
            rowKey={(run) => String(run.run_id)}
            loading={isLoading}
            loadingRows={3}
            empty={<span>No runs found.</span>}
          />
        </div>
      )}
    </Panel>
  );
}

export function ExperimentsTab({
  env,
  pipeline,
  project,
}: {
  env?: string;
  pipeline?: string;
  project?: string;
}) {
  const { data, isLoading, isError, refetch } = useMlopsExperiments(env, pipeline, project);
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

  if (!pipeline) {
    return (
      <EmptyState
        icon={IconFlask}
        title="Select a pipeline to view experiments"
        description="Pick an ML pipeline above to see its tracked experiments and runs."
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

      {isLoading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Skeleton variant="block" height="64px" />
          <Skeleton variant="block" height="64px" />
          <Skeleton variant="block" height="64px" />
        </div>
      )}
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
          env={env}
          pipeline={pipeline}
          project={project}
        />
      ))}

      {openRun && <RunDetailPanel run={openRun} onClose={() => setOpenRun(null)} />}
      {showCompare && (
        <RunCompareModal runs={[...compareSelection.values()]} onClose={() => setShowCompare(false)} />
      )}
    </div>
  );
}
