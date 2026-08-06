import { useNavigate } from "react-router-dom";
import { IconGauge, IconPlayerStop, IconRefresh, IconShieldCheck } from "@tabler/icons-react";
import { StatusBadge } from "../../components/ui/StatusBadge";
import type { DataTableColumn } from "../../components/ui/DataTable";
import { useCancelExecution, useRetryExecution } from "../../api/mutations";
import { formatDuration, formatTime } from "./helpers";
import "./executionTable.css";

export interface ExecutionListItem {
  id: string;
  status: string;
  pipeline_name: string;
  node_name?: string;
  project_id?: string;
  env: string;
  started_at?: string;
  duration_seconds?: number;
  dry_run?: boolean;
  sweep_id?: string;
  sweep_index?: number;
  certificate_run_id?: string;
}

export function isActiveExecution(execution: ExecutionListItem): boolean {
  return execution.status === "running" || execution.status === "pending";
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
}: Readonly<{
  execution: ExecutionListItem;
  onShowCertificate: (projectId: string, runId: string) => void;
}>) {
  const navigate = useNavigate();
  const { mutate: cancel, isPending: isCancelling } = useCancelExecution();
  const { mutate: retry, isPending: isRetrying } = useRetryExecution();

  const active = isActiveExecution(execution);
  const retryable = ["failed", "cancelled", "skipped"].includes(execution.status);
  const shortId = execution.id.slice(0, 8);

  return (
    // The row itself navigates; these buttons must not also trigger that.
    <div className="exec-actions" onClick={(e) => e.stopPropagation()}>
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
              )}`
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
  onShowCertificate: (projectId: string, runId: string) => void
): DataTableColumn<ExecutionListItem>[] {
  return [
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
      cell: (ex) => (
        <span className="exec-pipeline">
          {ex.pipeline_name}
          {ex.node_name && <span className="exec-node">[{ex.node_name}]</span>}
          {ex.sweep_id && (
            <span className="exec-sweep" title={`Sweep ${ex.sweep_id}`}>
              sweep{ex.sweep_index != null ? ` #${ex.sweep_index}` : ""}
            </span>
          )}
        </span>
      ),
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
      cell: (ex) => formatTime(ex.started_at),
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
      cell: (ex) => <ExecutionActions execution={ex} onShowCertificate={onShowCertificate} />,
    },
  ];
}
