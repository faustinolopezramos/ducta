import { useMemo, useState } from "react";
import type { Pipeline, ProjectSummary } from "../../types";
import { useExecutionList } from "../../api/queries";
import { Button } from "../../components/ui/Button";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { EmptyState } from "../../components/ui/EmptyState";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { compactDuration } from "../../utils/nodePresentation";
import { activityWindowStart, runTimestamp, type RunLike } from "../../utils/dashboardStats";
import { FAILURE_STATUSES } from "../../components/ui/statusMeta";
import { formatRelative } from "../../utils/timeLabels";
import { IconPlus, IconTrash, IconPlayerPlay, IconSitemap } from "@tabler/icons-react";

export interface PipelineSpecLike {
  type?: string;
  description?: string;
}

interface PipelineRow {
  id: string;
  name: string;
  type: string;
  description?: string;
  nodes: number;
  lastRun: RunLike | null;
  runsThisWeek: number;
}

/**
 * A project's pipelines as a table: what each one is, how big, and how its
 * last run went. It replaces a grid of identical cards whose run and delete
 * buttons stayed invisible until hover, and whose delete asked "Yes / No" in an
 * overlay on top of the card it was deleting.
 */
export function PipelinesView({
  projectId,
  project,
  pipelines,
  specs,
  onOpen,
  onRun,
  onDelete,
  onCreate,
}: {
  projectId: string;
  project: ProjectSummary;
  pipelines: Pipeline[];
  specs: Record<string, PipelineSpecLike | undefined>;
  onOpen: (pipelineId: string) => void;
  onRun: (pipelineId: string) => void;
  onDelete: (pipelineId: string) => void;
  onCreate: () => void;
}) {
  // Fixed for the life of the view so the query key does not change every render.
  const [since] = useState(activityWindowStart);
  const { data: runsData, isLoading } = useExecutionList({ project_id: projectId, since, limit: 200 });

  const rows = useMemo<PipelineRow[]>(() => {
    const runs = ((runsData?.executions ?? []) as RunLike[])
      .map((run) => ({ run, t: runTimestamp(run) ?? 0 }))
      .sort((a, b) => b.t - a.t);
    return pipelines.map((pipeline) => {
      const spec = specs[pipeline.id];
      const own = runs.filter((x) => x.run.pipeline_name === pipeline.id);
      return {
        id: pipeline.id,
        name: pipeline.name || pipeline.id,
        type: spec?.type ?? pipeline.type ?? "batch",
        description: spec?.description ?? pipeline.description,
        nodes: pipeline.nodes.length,
        lastRun: own[0]?.run ?? null,
        runsThisWeek: own.length,
      };
    });
  }, [runsData, pipelines, specs]);

  const columns: DataTableColumn<PipelineRow>[] = [
    {
      key: "name",
      header: "Pipeline",
      cell: (r) => (
        <span className="dash-table-project">
          <span className="project-list-name">{r.name}</span>
          {r.description && <span className="project-list-desc">{r.description}</span>}
        </span>
      ),
    },
    {
      key: "type",
      header: "Type",
      width: "110px",
      cell: (r) => <span className="pipeline-type-tag">{r.type}</span>,
    },
    { key: "nodes", header: "Nodes", align: "right", mono: true, width: "80px", cell: (r) => r.nodes },
    {
      key: "last",
      header: "Last run",
      width: "230px",
      cell: (r) =>
        r.lastRun ? (
          <span className="dash-table-last">
            <StatusBadge status={r.lastRun.status} size="sm" />
            <span>
              {formatRelative(r.lastRun.started_at ?? r.lastRun.finished_at)}
              {r.lastRun.duration_seconds != null ? ` · ${compactDuration(r.lastRun.duration_seconds)}` : ""}
            </span>
          </span>
        ) : (
          <span className="dash-muted">{isLoading ? "…" : "No runs this week"}</span>
        ),
    },
    { key: "runs", header: "Runs · 7 d", align: "right", mono: true, width: "96px", cell: (r) => r.runsThisWeek },
    {
      key: "actions",
      header: "",
      headerLabel: "Actions",
      align: "right",
      width: "96px",
      cell: (r) => (
        <span className="project-list-actions">
          <button
            type="button"
            className="dash-menu-trigger"
            aria-label={`Run ${r.name}`}
            title="Run pipeline"
            onClick={(e) => {
              e.stopPropagation();
              onRun(r.id);
            }}
          >
            <IconPlayerPlay size={15} stroke={1.75} />
          </button>
          <button
            type="button"
            className="dash-menu-trigger project-list-delete"
            aria-label={`Delete ${r.name}`}
            title="Delete pipeline"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(r.id);
            }}
          >
            <IconTrash size={15} stroke={1.75} />
          </button>
        </span>
      ),
    },
  ];

  return (
    <div className="project-content project-list t-container">
      <header className="project-list-head">
        <h1 className="project-list-title">{project.name}</h1>
        <p className="project-list-meta">
          <span className="project-list-id">{project.id}</span> · {pipelines.length} pipeline
          {pipelines.length !== 1 ? "s" : ""}
        </p>
      </header>

      {pipelines.length === 0 ? (
        <EmptyState
          icon={IconSitemap}
          title="No pipelines yet"
          description="Create a pipeline, then add nodes to it on the canvas."
          action={
            <Button variant="primary" onClick={onCreate} leftIcon={<IconPlus size={16} stroke={2} />}>
              New pipeline
            </Button>
          }
        />
      ) : (
        <DataTable<PipelineRow>
          columns={columns}
          rows={rows}
          rowKey={(r) => r.id}
          onRowClick={(r) => onOpen(r.id)}
          rowClassName={(r) =>
            r.lastRun && FAILURE_STATUSES.has(r.lastRun.status) ? "dash-row--failing" : undefined
          }
          minWidth={760}
          caption={`Pipelines of ${project.name}`}
        />
      )}
    </div>
  );
}
