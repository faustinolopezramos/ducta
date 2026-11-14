import { useNavigate } from "react-router-dom";
import { IconClock, IconPencil, IconPlayerPause, IconPlayerPlay, IconTrash } from "@tabler/icons-react";
import type { DataTableColumn } from "../../components/ui/DataTable";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { useToggleSchedule, type PipelineSchedule } from "../../api/schedulesApi";
import { describeCron } from "../../utils/cron";
import { formatRelative, formatUtc } from "../../utils/timeLabels";
import { usePermission } from "../../hooks/usePermission";

/**
 * Per-row actions. Its own component because it needs the toggle mutation
 * hook, which a column's `cell` function cannot call — same pattern as
 * `ExecutionActions` in ExecutionHistoryPage/executionColumns.tsx. Each row
 * owns its own mutation instance so one schedule's pending toggle never
 * shows as loading on another row.
 */
function ScheduleActions({
  schedule,
  onEdit,
  onDelete,
}: Readonly<{
  schedule: PipelineSchedule;
  onEdit: (schedule: PipelineSchedule) => void;
  onDelete: (schedule: PipelineSchedule) => void;
}>) {
  const toggleMutation = useToggleSchedule();
  // Pausing, editing and deleting a schedule all need execution.write.
  const canWrite = usePermission("execution.write");
  if (!canWrite) return null;

  return (
    <div className="schedule-actions" role="presentation" onClick={(e) => e.stopPropagation()}>
      <button
        className="schedule-action"
        title={schedule.enabled ? "Pause schedule" : "Enable schedule"}
        aria-label={`${schedule.enabled ? "Pause" : "Enable"} schedule for ${schedule.pipeline_name}`}
        onClick={() => toggleMutation.mutate({ id: schedule.id, enabled: !schedule.enabled })}
        disabled={toggleMutation.isPending}
      >
        {toggleMutation.isPending ? (
          <span className="schedule-action__spinner" aria-hidden="true" />
        ) : schedule.enabled ? (
          <IconPlayerPause size={13} />
        ) : (
          <IconPlayerPlay size={13} />
        )}
      </button>
      <button
        className="schedule-action"
        title="Edit schedule"
        aria-label={`Edit schedule for ${schedule.pipeline_name}`}
        onClick={() => onEdit(schedule)}
      >
        <IconPencil size={13} />
      </button>
      <button
        className="schedule-action schedule-action--danger"
        title="Delete schedule"
        aria-label={`Delete schedule for ${schedule.pipeline_name}`}
        onClick={() => onDelete(schedule)}
      >
        <IconTrash size={13} />
      </button>
    </div>
  );
}

function LastRunCell({ schedule }: Readonly<{ schedule: PipelineSchedule }>) {
  const navigate = useNavigate();
  if (!schedule.last_run_at) return <span className="schedule-time">never</span>;

  return (
    <button
      className="schedule-lastrun-link"
      title={schedule.last_execution_id ? "View this run in Execution History" : undefined}
      disabled={!schedule.last_execution_id}
      onClick={(e) => {
        e.stopPropagation();
        if (schedule.last_execution_id) {
          navigate(`/workspace/executions?run=${encodeURIComponent(schedule.last_execution_id)}`);
        }
      }}
    >
      <span className="schedule-time">{formatUtc(schedule.last_run_at)}</span>
      <span className="schedule-time-relative">{formatRelative(schedule.last_run_at)}</span>
    </button>
  );
}

export function scheduleColumns(
  onEdit: (schedule: PipelineSchedule) => void,
  onDelete: (schedule: PipelineSchedule) => void
): DataTableColumn<PipelineSchedule>[] {
  return [
    {
      key: "enabled",
      header: "Status",
      sortable: true,
      sortValue: (s) => (s.enabled ? 1 : 0),
      cell: (s) => (
        <StatusBadge status={s.enabled ? "success" : "idle"} label={s.enabled ? "Active" : "Paused"} size="sm" />
      ),
    },
    {
      key: "pipeline_name",
      header: "Pipeline",
      sortable: true,
      mono: true,
      cell: (s) => (
        <span>
          {s.pipeline_name}
          {s.node_name && <span className="schedule-node">[{s.node_name}]</span>}
        </span>
      ),
    },
    {
      key: "project_id",
      header: "Project / Env",
      sortable: true,
      mono: true,
      cell: (s) => `${s.project_id ?? "—"} · ${s.env}`,
    },
    {
      key: "cron",
      header: "Schedule",
      cell: (s) => (
        <div className="schedule-cron">
          <span className="schedule-cron__raw">
            <IconClock size={13} aria-hidden="true" />
            <code>{s.cron}</code>
          </span>
          <span className="schedule-cron__desc">{describeCron(s.cron)}</span>
        </div>
      ),
    },
    {
      key: "next_run_at",
      header: "Next run",
      sortable: true,
      mono: true,
      cell: (s) =>
        s.enabled && s.next_run_at ? (
          <span>
            <span className="schedule-time">{formatUtc(s.next_run_at)}</span>{" "}
            <span className="schedule-time-relative">{formatRelative(s.next_run_at)}</span>
          </span>
        ) : (
          <span className="schedule-time">—</span>
        ),
    },
    {
      key: "last_run_at",
      header: "Last run",
      sortable: true,
      cell: (s) => <LastRunCell schedule={s} />,
    },
    {
      key: "actions",
      header: "",
      headerLabel: "Schedule actions",
      align: "right",
      cell: (s) => <ScheduleActions schedule={s} onEdit={onEdit} onDelete={onDelete} />,
    },
  ];
}
