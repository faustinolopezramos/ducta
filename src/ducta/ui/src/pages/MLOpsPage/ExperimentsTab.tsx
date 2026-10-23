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
  useMlopsStatus,
  useMlopsRunTable,
  useCloseMlopsRun,
  useDeleteMlopsRun,
  lastMetricValues,
  type ExperimentSummary,
  type ExperimentRun,
  type RunTableRow,
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
  IconDownload,
} from "@tabler/icons-react";
import { findProjectForPipeline } from "./shared";
import { MlopsEmptyState } from "./MlopsDiagnosis";
import { RunStatusLabel } from "./RunBits";
import { RunTableView } from "./RunTableView";
import { downloadText, runTableToCsv } from "./runTable";
import { formatDate } from "../../utils/formatDate";
import { routes } from "../../utils/routes";

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
    navigate(routes.pipeline(projectId, pipelineName));
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
        <span style={{ fontSize: "var(--text-xs)", color: colors.textMuted }}>{formatDate(exp.created_at, { includeYear: true })}</span>
        <span style={{ fontSize: "var(--text-2xs)", color: colors.textMuted, fontFamily: "var(--font-mono)" }}>
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

/** The detail panel of a run chosen in the run table: the table row only has the final
 *  values, so the full run (tags, Ducta's own parameters) is read from its experiment. */
function OpenedRunRow({
  row,
  experiments,
  env,
  pipeline,
  project,
  onClose,
}: {
  row: RunTableRow;
  experiments: ExperimentSummary[];
  env?: string;
  pipeline?: string;
  project?: string;
  onClose: () => void;
}) {
  const experimentId = experiments.find((e) => e.name === row.pipeline)?.experiment_id ?? "";
  const { data: detail } = useMlopsExperiment(experimentId, env, pipeline, project);
  const run = detail?.runs.find((r) => r.run_id === row.run_id);
  if (!run) return null;
  return <RunDetailPanel run={run} onClose={onClose} evidence={row} project={project} />;
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
  const { data: status } = useMlopsStatus(env, pipeline, project);
  const { data: runTable } = useMlopsRunTable(env, pipeline, project);
  const [view, setView] = useState<"experiments" | "runs">("experiments");
  const [compareSelection, setCompareSelection] = useState<Map<string, ExperimentRun>>(new Map());
  const [openRun, setOpenRun] = useState<ExperimentRun | null>(null);
  const [openRow, setOpenRow] = useState<RunTableRow | null>(null);
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
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div className="mlops-view-switch" role="group" aria-label="Experiments view">
            <Button
              size="sm"
              variant={view === "experiments" ? "primary" : "ghost"}
              aria-pressed={view === "experiments"}
              onClick={() => setView("experiments")}
            >
              By experiment
            </Button>
            <Button
              size="sm"
              variant={view === "runs" ? "primary" : "ghost"}
              aria-pressed={view === "runs"}
              onClick={() => setView("runs")}
            >
              All runs
            </Button>
          </div>
          <span style={{ fontSize: "var(--text-sm)", color: colors.textMuted }}>
            {view === "runs"
              ? `${runTable?.rows.length ?? 0} run${runTable?.rows.length === 1 ? "" : "s"}`
              : `${experiments.length} experiment${experiments.length !== 1 ? "s" : ""}`}
            {compareSelection.size > 0 && ` · ${compareSelection.size} run(s) selected`}
          </span>
        </div>
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
          {view === "runs" && runTable && runTable.rows.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<IconDownload size={14} />}
              title="Every column of the run table, as CSV"
              onClick={() =>
                downloadText(
                  `${pipeline}-runs.csv`,
                  runTableToCsv(runTable.columns, runTable.rows)
                )
              }
            >
              CSV
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => refetch()} leftIcon={<IconRefresh size={14} />}>
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
        <div style={{ color: "var(--danger)", fontSize: "var(--text-sm)" }}>
          Failed to load experiments. Check that MLOps is configured in the workspace.
        </div>
      )}
      {!isLoading && !isError && experiments.length === 0 && (
        <MlopsEmptyState status={status} env={env} what="experiments" icon={IconFlask} />
      )}
      {view === "runs" && runTable && experiments.length > 0 && (
        <RunTableView
          table={runTable}
          selection={compareSelection}
          onToggle={toggleCompare}
          onOpen={setOpenRow}
          project={project}
        />
      )}
      {view === "experiments" && experiments.map((exp) => (
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

      {openRun && (
        <RunDetailPanel
          run={openRun}
          onClose={() => setOpenRun(null)}
          evidence={runTable?.rows.find((r) => r.run_id === openRun.run_id)}
          project={project}
        />
      )}
      {openRow && (
        <OpenedRunRow
          row={openRow}
          experiments={experiments}
          env={env}
          pipeline={pipeline}
          project={project}
          onClose={() => setOpenRow(null)}
        />
      )}
      {showCompare && (
        <RunCompareModal runs={[...compareSelection.values()]} onClose={() => setShowCompare(false)} />
      )}
    </div>
  );
}
