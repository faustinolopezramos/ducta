import { useState } from "react";
import {
  IconCalendarEvent,
  IconClock,
  IconPlus,
  IconTrash,
  IconPlayerPause,
  IconPlayerPlay,
} from "@tabler/icons-react";
import { useSchedules, useCreateSchedule, useDeleteSchedule, useToggleSchedule } from "../api/schedulesApi";
import { useEnvironments, useServerProjects, useServerProjectPipelines } from "../api/queries";
import { Button, Modal, PageHeader, PageContainer, StatusBadge, EmptyState, Skeleton, ConfirmDialog } from "../components/ui";

export function SchedulesPage() {
  const { data, isLoading, isError, refetch } = useSchedules();
  const createMutation = useCreateSchedule();
  const deleteMutation = useDeleteSchedule();
  const toggleMutation = useToggleSchedule();

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [scheduleToDelete, setScheduleToDelete] = useState<string | null>(null);
  // The user's explicit pick; empty until they choose one. The project actually
  // in force is `projectId` or, before any pick, the first one that loaded —
  // derived below rather than written back into state from an effect, which
  // cost a second render pass on every load.
  const [pickedProjectId, setPickedProjectId] = useState("");
  const [pipelineName, setPipelineName] = useState("");
  const [cron, setCron] = useState("0 0 * * *");
  const [env, setEnv] = useState("base");

  const { data: projectsData } = useServerProjects();
  const projects = projectsData?.projects ?? [];
  const projectId = pickedProjectId || projects[0]?.id || "";
  const { data: pipelinesData } = useServerProjectPipelines(projectId);
  const { data: environmentsData } = useEnvironments();
  const availablePipelines = Object.keys(pipelinesData?.pipelines ?? {});
  const environments = environmentsData?.environments?.length ? environmentsData.environments : ["base"];


  const handleCreate = () => {
    if (!projectId || !pipelineName || !cron) return;
    createMutation.mutate(
      {
        pipeline_name: pipelineName,
        project_id: projectId,
        cron,
        env,
      },
      {
        onSuccess: () => {
          setShowCreateModal(false);
          setPickedProjectId("");
          setPipelineName("");
        },
      }
    );
  };

  return (
    <PageContainer>
      <PageHeader
        title="Automated Schedules"
        description="Configure autonomous background pipeline triggers powered by Ducta AsyncCronScheduler."
        actions={
          <Button variant="primary" onClick={() => setShowCreateModal(true)}>
            <IconPlus size={16} /> New Schedule
          </Button>
        }
      />

      {isLoading ? (
        <div className="schedules-grid">
          <Skeleton variant="block" height="180px" />
          <Skeleton variant="block" height="180px" />
        </div>
      ) : isError ? (
        // A failed fetch must not read as "nothing is scheduled" — it used to
        // fall straight into the empty state below.
        <EmptyState
          icon={IconCalendarEvent}
          title="Couldn't load schedules"
          description="Check that the API is reachable and try again."
          action={<Button variant="ghost" onClick={() => refetch()}>Refresh</Button>}
        />
      ) : !data?.schedules || data.schedules.length === 0 ? (
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
        <div className="schedules-grid">
          {data.schedules.map((sched) => (
            <article key={sched.id} className="schedule-card">
              <header className="schedule-card__head">
                <div className="schedule-card__id">
                  <h4 className="schedule-card__pipeline">{sched.pipeline_name}</h4>
                  <span className="schedule-card__scope">
                    {sched.project_id ? `Project: ${sched.project_id} · ` : ""}Environment: {sched.env}
                  </span>
                </div>
                <StatusBadge
                  status={sched.enabled ? "success" : "idle"}
                  label={sched.enabled ? "Active" : "Paused"}
                  size="sm"
                />
              </header>

              <div className="schedule-card__cron">
                <IconClock size={15} aria-hidden="true" />
                <code>{sched.cron}</code>
              </div>

              <div className="schedule-card__lastrun">
                Last run: {sched.last_run_at ? new Date(sched.last_run_at).toLocaleString() : "never"}
              </div>

              <div className="schedule-card__actions">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => toggleMutation.mutate({ id: sched.id, enabled: !sched.enabled })}
                >
                  {sched.enabled ? <IconPlayerPause size={14} /> : <IconPlayerPlay size={14} />}
                  {sched.enabled ? "Pause" : "Enable"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setScheduleToDelete(sched.id)}
                  aria-label={`Delete schedule for ${sched.pipeline_name}`}
                  title={`Delete schedule for ${sched.pipeline_name}`}
                  iconOnly
                >
                  <IconTrash size={14} color="var(--danger)" />
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}

      {showCreateModal && (
        <Modal title="Create pipeline schedule" onClose={() => setShowCreateModal(false)} width={460}>
          <div className="projects-modal__form">
            <label className="projects-modal__label" htmlFor="schedule-project">Project</label>
            <select id="schedule-project" className="projects-modal__select" value={projectId} onChange={(e) => { setPickedProjectId(e.target.value); setPipelineName(""); }}>
              <option value="">Select a project</option>
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>

            <label className="projects-modal__label" htmlFor="schedule-pipeline" style={{ marginTop: 12 }}>Pipeline</label>
            <select
              id="schedule-pipeline"
              className="projects-modal__select"
              value={pipelineName}
              onChange={(e) => setPipelineName(e.target.value)}
              disabled={!projectId}
            >
              <option value="">{projectId ? "Select a pipeline" : "Select a project first"}</option>
              {availablePipelines.map((pipeline) => <option key={pipeline} value={pipeline}>{pipeline}</option>)}
            </select>

            <label className="projects-modal__label" htmlFor="schedule-cron" style={{ marginTop: 12 }}>Cron expression (5 fields)</label>
            <input
              id="schedule-cron"
              className="projects-modal__input"
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              placeholder="0 0 * * *"
            />
            <p className="projects-modal__hint">
              Examples: <code>0 0 * * *</code> (midnight), <code>*/15 * * * *</code> (every 15m), <code>0 8 * * 1</code> (Mondays 8AM)
            </p>

            <label className="projects-modal__label" htmlFor="schedule-environment" style={{ marginTop: 12 }}>Environment</label>
            <select id="schedule-environment" className="projects-modal__select" value={env} onChange={(e) => setEnv(e.target.value)}>
              {environments.map((environment: string) => <option key={environment} value={environment}>{environment}</option>)}
            </select>

            <div className="projects-modal__actions" style={{ marginTop: 20 }}>
              <Button variant="ghost" onClick={() => setShowCreateModal(false)}>Cancel</Button>
              <Button variant="primary" onClick={handleCreate} loading={createMutation.isPending} disabled={!projectId || !pipelineName || !cron}>
                {createMutation.isPending ? "Creating…" : "Schedule Pipeline"}
              </Button>
            </div>
          </div>
        </Modal>
      )}

      <ConfirmDialog
        open={!!scheduleToDelete}
        title={
          scheduleToDelete
            ? `Delete schedule for ${data?.schedules?.find((s) => s.id === scheduleToDelete)?.pipeline_name ?? scheduleToDelete}?`
            : "Delete schedule?"
        }
        description="This schedule will stop running automatically. Existing execution history is preserved."
        tone="danger"
        confirmLabel="Delete schedule"
        pending={deleteMutation.isPending}
        onConfirm={() =>
          scheduleToDelete &&
          deleteMutation.mutate(scheduleToDelete, { onSuccess: () => setScheduleToDelete(null) })
        }
        onCancel={() => setScheduleToDelete(null)}
      />
    </PageContainer>
  );
}

export default SchedulesPage;
