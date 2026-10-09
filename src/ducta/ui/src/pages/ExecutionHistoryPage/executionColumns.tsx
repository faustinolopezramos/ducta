import { useNavigate } from "react-router-dom";
import { IconAlertTriangle, IconGauge, IconPlayerStop, IconRefresh, IconShieldCheck } from "@tabler/icons-react";
import { StatusBadge } from "../../components/ui/StatusBadge";
import type { DataTableColumn } from "../../components/ui/DataTable";
import { useCancelExecution, useRetryExecution } from "../../api/mutations";
import { formatDuration } from "./helpers";
import { formatDate } from "../../utils/formatDate";
import "./executionTable.css";

export interface ExecutionListItem {
  id: string;
  status: string;
  pipeline_name: string;
  node_name?: string;
  project_id?: string;
  env: string;
  started_at?: string;
  finished_at?: string;
  duration_seconds?: number;
  exit_code?: number;
  error_message?: string;
  model_version?: string;
  dry_run?: boolean;
  sweep_id?: string;
  sweep_index?: number;
  certificate_run_id?: string;
}

export function isActiveExecution(execution: ExecutionListItem): boolean {
  return execution.status === "running" || execution.status === "pending";
}

export interface SweepStats {
  total: number;
  success: number;
  failed: number;
  running: number;
}

/** Aggregates per sweep_id, computed once over the currently-loaded rows —
 *  what powers the sweep summary in `ExecutionRowDetail` and the badge
 *  count next to each member's "sweep #N" tag. */
export function computeSweepStats(executions: ExecutionListItem[]): Map<string, SweepStats> {
  const stats = new Map<string, SweepStats>();
  for (const ex of executions) {
    if (!ex.sweep_id) continue;
    const s = stats.get(ex.sweep_id) ?? { total: 0, success: 0, failed: 0, running: 0 };
    s.total += 1;
    if (ex.status === "success") s.success += 1;
    else if (ex.status === "failed") s.failed += 1;
    else if (isActiveExecution(ex)) s.running += 1;
    stats.set(ex.sweep_id, s);
  }
  return stats;
}

/**
 * Per-row actions.
 *
 * Its own component because it owns mutation hooks, which a column's `cell`
 * function cannot call.
 */
function ExecutionActions({
  execution,
  onShowCertificate,
  onToggleDetail,
  detailOpen,
}: Readonly<{
  execution: ExecutionListItem;
  onShowCertificate: (projectId: string, runId: string) => void;
  onToggleDetail: (id: string) => void;
  detailOpen: boolean;
}>) {
  const navigate = useNavigate();
  const { mutate: cancel, isPending: isCancelling } = useCancelExecution();
  const { mutate: retry, isPending: isRetrying } = useRetryExecution();

  const active = isActiveExecution(execution);
  const retryable = ["failed", "cancelled", "skipped"].includes(execution.status);
  const shortId = execution.id.slice(0, 8);

  return (
    // The row itself navigates; these buttons must not also trigger that.
    <div className="exec-actions" role="presentation" onClick={(e) => e.stopPropagation()}>
      {execution.status === "failed" && execution.error_message && (
        <button
          className="exec-action exec-action--danger"
          title={detailOpen ? "Hide error" : "Preview error without opening the full log"}
          aria-label={detailOpen ? `Hide error for execution ${shortId}` : `Preview error for execution ${shortId}`}
          aria-expanded={detailOpen}
          onClick={() => onToggleDetail(execution.id)}
        >
          <IconAlertTriangle size={12} />
        </button>
      )}
      {active && (
        <button
          className="exec-action exec-action--danger"
          title="Cancel execution"
          aria-label={`Cancel execution ${shortId}`}
          onClick={() => cancel(execution.id)}
          disabled={isCancelling}
        >
          <IconPlayerStop size={12} />
        </button>
      )}
      {retryable && (
        <button
          className="exec-action"
          title="Retry execution"
          aria-label={`Retry execution ${shortId}`}
          onClick={() => retry(execution.id)}
          disabled={isRetrying}
        >
          <IconRefresh size={12} />
        </button>
      )}
      {!active && !execution.dry_run && (
        <button
          className="exec-action"
          title="Pipeline quality score for this run"
          aria-label={`Quality score for execution ${shortId}`}
          onClick={() =>
            navigate(
              `/workspace/quality?run_id=${encodeURIComponent(
                execution.certificate_run_id ?? execution.id
              )}&env=${encodeURIComponent(execution.env)}&pipeline_name=${encodeURIComponent(
                execution.pipeline_name
              )}&project=${encodeURIComponent(execution.project_id ?? "")}`
            )
          }
        >
          <IconGauge size={12} />
        </button>
      )}
      {execution.certificate_run_id && execution.project_id && (
        <button
          className="exec-action exec-action--accent"
          title="View Run Certificate (tamper-evident proof of this run)"
          aria-label={`View run certificate for execution ${shortId}`}
          onClick={() => onShowCertificate(execution.project_id!, execution.certificate_run_id!)}
        >
          <IconShieldCheck size={12} />
        </button>
      )}
    </div>
  );
}

export function executionColumns(
  onShowCertificate: (projectId: string, runId: string) => void,
  onToggleDetail: (id: string) => void,
  expandedId: string | null,
  sweepStats: Map<string, SweepStats>,
  { showProject = true }: { showProject?: boolean } = {},
): DataTableColumn<ExecutionListItem>[] {
  const columns: DataTableColumn<ExecutionListItem>[] = [
    {
      key: "status",
      header: "Status",
      sortable: true,
      cell: (ex) => <StatusBadge status={ex.status} size="sm" />,
    },
    {
      key: "pipeline_name",
      header: "Pipeline",
      sortable: true,
      cell: (ex) => {
        const stats = ex.sweep_id ? sweepStats.get(ex.sweep_id) : undefined;
        return (
          <span className="exec-pipeline">
            {ex.pipeline_name}
            {ex.node_name && <span className="exec-node">[{ex.node_name}]</span>}
            {ex.sweep_id && (
              <button
                className="exec-sweep"
                title={`Sweep ${ex.sweep_id}${stats ? ` — ${stats.total} runs` : ""}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleDetail(ex.id);
                }}
              >
                sweep{ex.sweep_index != null ? ` #${ex.sweep_index}` : ""}
                {stats && stats.total > 1 ? ` · ${stats.total}` : ""}
              </button>
            )}
          </span>
        );
      },
    },
    {
      key: "project_id",
      header: "Project",
      sortable: true,
      mono: true,
      cell: (ex) => ex.project_id ?? "—",
    },
    {
      key: "env",
      header: "Env",
      sortable: true,
      mono: true,
      cell: (ex) => (
        <>
          {ex.env}
          {ex.dry_run && <span className="exec-dry">dry</span>}
        </>
      ),
    },
    {
      key: "started_at",
      header: "Started",
      sortable: true,
      mono: true,
      cell: (ex) => formatDate(ex.started_at),
    },
    {
      key: "duration_seconds",
      header: "Duration",
      sortable: true,
      align: "right",
      mono: true,
      cell: (ex) => formatDuration(ex.duration_seconds),
    },
    {
      key: "id",
      header: "ID",
      mono: true,
      cell: (ex) => ex.id.slice(0, 8),
    },
    {
      key: "actions",
      header: "",
      headerLabel: "Execution actions",
      align: "right",
      cell: (ex) => (
        <ExecutionActions
          execution={ex}
          onShowCertificate={onShowCertificate}
          onToggleDetail={onToggleDetail}
          detailOpen={expandedId === ex.id}
        />
      ),
    },
  ];
  // Under a project every row is that project's: the column only repeats it.
  return showProject ? columns : columns.filter((c) => c.key !== "project_id");
}

/** The row detail shown by DataTable's `renderRowDetail`: a quick error
 *  snippet in place (no need to open the full log drawer just to see what
 *  went wrong) and/or, for a sweep member, the sweep's aggregate outcome —
 *  context that's otherwise invisible when every run in a sweep shows up as
 *  an unrelated-looking row. */
export function ExecutionRowDetail({
  execution,
  sweepStats,
}: Readonly<{ execution: ExecutionListItem; sweepStats: Map<string, SweepStats> }>) {
  const stats = execution.sweep_id ? sweepStats.get(execution.sweep_id) : undefined;
  return (
    <div
      role="presentation"
      onClick={(e) => e.stopPropagation()}
      style={{ fontFamily: "var(--font-mono)", fontSize: 11, display: "flex", flexDirection: "column", gap: 6 }}
    >
      {stats && (
        <div style={{ color: "var(--text-muted)" }}>
          Sweep {execution.sweep_id} — {stats.total} runs:{" "}
          <span style={{ color: "var(--success)" }}>{stats.success} success</span>,{" "}
          <span style={{ color: "var(--danger)" }}>{stats.failed} failed</span>
          {stats.running > 0 && (
            <>
              , <span style={{ color: "var(--primary)" }}>{stats.running} running</span>
            </>
          )}
        </div>
      )}
      {execution.error_message && (
        <div style={{ color: "var(--danger)", whiteSpace: "pre-wrap" }}>{execution.error_message}</div>
      )}
    </div>
  );
}
