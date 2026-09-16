import { useMemo, useState } from "react";
import { IconCalendarEvent, IconPlus, IconSearch } from "@tabler/icons-react";
import { useSchedules, useDeleteSchedule, type PipelineSchedule } from "../../api/schedulesApi";
import { Button, PageHeader, PageContainer, EmptyState, DataTable, ConfirmDialog } from "../../components/ui";
import { scheduleColumns } from "./scheduleColumns";
import { ScheduleFormModal } from "./ScheduleFormModal";
import "./schedules.css";

type StatusFilter = "all" | "active" | "paused";

export function SchedulesPage() {
  const { data, isLoading, isError, refetch } = useSchedules();
  const deleteMutation = useDeleteSchedule();

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<PipelineSchedule | null>(null);
  const [scheduleToDelete, setScheduleToDelete] = useState<PipelineSchedule | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const schedules = data?.schedules;
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (schedules ?? []).filter((s) => {
      if (statusFilter === "active" && !s.enabled) return false;
      if (statusFilter === "paused" && s.enabled) return false;
      if (q && !s.pipeline_name.toLowerCase().includes(q) && !(s.project_id ?? "").toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
  }, [schedules, search, statusFilter]);

  return (
    <PageContainer>
      <PageHeader
        title="Automated Schedules"
        description="Configure autonomous background pipeline triggers powered by Ducta AsyncCronScheduler. Cron expressions run in UTC."
        actions={
          <Button variant="primary" onClick={() => setShowCreateModal(true)}>
            <IconPlus size={16} /> New Schedule
          </Button>
        }
      />

      {isError ? (
        <EmptyState
          icon={IconCalendarEvent}
          title="Couldn't load schedules"
          description="Check that the API is reachable and try again."
          action={<Button variant="ghost" onClick={() => refetch()}>Refresh</Button>}
        />
      ) : !isLoading && (schedules?.length ?? 0) === 0 ? (
        <EmptyState
          icon={IconCalendarEvent}
          title="No automated schedules"
          description="Set up cron expressions to automatically run data pipelines at scheduled intervals."
          action={
            <Button variant="primary" onClick={() => setShowCreateModal(true)}>
              <IconPlus size={16} /> Create First Schedule
            </Button>
          }
        />
      ) : (
        <>
          <div className="schedules-filterbar">
            <div className="schedules-search">
              <IconSearch size={13} aria-hidden="true" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search pipeline or project…"
                aria-label="Search schedules"
              />
            </div>
            <div className="schedules-status-pills">
              {(["all", "active", "paused"] as StatusFilter[]).map((s) => (
                <button
                  key={s}
                  className="schedules-status-pill"
                  aria-pressed={statusFilter === s}
                  onClick={() => setStatusFilter(s)}
                >
                  {s === "all" ? "All" : s === "active" ? "Active" : "Paused"}
                </button>
              ))}
            </div>
          </div>

          <DataTable<PipelineSchedule>
            columns={scheduleColumns(setEditingSchedule, setScheduleToDelete)}
            rows={filtered}
            rowKey={(s) => s.id}
            minWidth={860}
            stickyHeader
            loading={isLoading}
            loadingRows={4}
            empty={
              <EmptyState
                icon={IconSearch}
                title="No schedules match these filters"
                description="Try a different search term or clear the status filter."
              />
            }
          />
        </>
      )}

      {(showCreateModal || editingSchedule) && (
        <ScheduleFormModal
          key={editingSchedule?.id ?? "create"}
          schedule={editingSchedule ?? undefined}
          onClose={() => {
            setShowCreateModal(false);
            setEditingSchedule(null);
          }}
        />
      )}

      <ConfirmDialog
        open={!!scheduleToDelete}
        title={scheduleToDelete ? `Delete schedule for ${scheduleToDelete.pipeline_name}?` : "Delete schedule?"}
        description="This schedule will stop running automatically. Existing execution history is preserved."
        tone="danger"
        confirmLabel="Delete schedule"
        pending={deleteMutation.isPending}
        onConfirm={() =>
          scheduleToDelete &&
          deleteMutation.mutate(scheduleToDelete.id, { onSuccess: () => setScheduleToDelete(null) })
        }
        onCancel={() => setScheduleToDelete(null)}
      />
    </PageContainer>
  );
}

export default SchedulesPage;
