import { useState } from "react";
import { IconChevronDown, IconChevronRight } from "@tabler/icons-react";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import { useEnvironments, useServerProjects, useServerProjectPipelines } from "../../api/queries";
import {
  useCreateSchedule,
  useUpdateSchedule,
  type PipelineSchedule,
} from "../../api/schedulesApi";
import { validateCron } from "../../utils/cron";
import { SchedulePicker } from "./SchedulePicker";

/** Shared by "New Schedule" and "Edit Schedule" — a schedule's project is
 *  fixed at creation (the backend has no way to move one to a different
 *  workspace/project), so edit mode shows it read-only and only lets the
 *  pipeline, cron, environment and advanced fields change. */
export function ScheduleFormModal({
  schedule,
  onClose,
}: Readonly<{ schedule?: PipelineSchedule; onClose: () => void }>) {
  const isEdit = !!schedule;
  const createMutation = useCreateSchedule();
  const updateMutation = useUpdateSchedule();
  const mutation = isEdit ? updateMutation : createMutation;

  const [pickedProjectId, setPickedProjectId] = useState("");
  const [pipelineName, setPipelineName] = useState(schedule?.pipeline_name ?? "");
  const [cron, setCron] = useState(schedule?.cron ?? "0 0 * * *");
  const [env, setEnv] = useState(schedule?.env ?? "base");
  const [nodeName, setNodeName] = useState(schedule?.node_name ?? "");
  const [hyperparamsText, setHyperparamsText] = useState(
    schedule?.hyperparams ? JSON.stringify(schedule.hyperparams, null, 2) : ""
  );
  const [showAdvanced, setShowAdvanced] = useState(!!(schedule?.node_name || schedule?.hyperparams));

  const { data: projectsData } = useServerProjects();
  const projects: { id: string; name?: string }[] = projectsData?.projects ?? [];
  // Edit mode: the project is fixed to the schedule's own — never silently
  // fall back to the first project the way this form used to for create mode.
  const projectId = isEdit ? schedule!.project_id ?? "" : pickedProjectId;
  const { data: pipelinesData } = useServerProjectPipelines(projectId);
  const { data: environmentsData } = useEnvironments();
  const availablePipelines: string[] = Object.keys(pipelinesData?.pipelines ?? {});
  const environments: string[] = environmentsData?.environments?.length ? environmentsData.environments : ["base"];

  const cronError = validateCron(cron);

  let hyperparams: Record<string, unknown> | undefined;
  let hyperparamsError: string | null = null;
  if (hyperparamsText.trim()) {
    try {
      const parsed = JSON.parse(hyperparamsText);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        hyperparams = parsed;
      } else {
        hyperparamsError = "Must be a JSON object, e.g. {\"key\": \"value\"}";
      }
    } catch {
      hyperparamsError = "Invalid JSON";
    }
  }

  const canSubmit =
    !!projectId && !!pipelineName && !cronError && !hyperparamsError && !mutation.isPending;

  const handleSubmit = () => {
    if (!canSubmit) return;
    if (isEdit) {
      updateMutation.mutate(
        {
          id: schedule!.id,
          pipeline_name: pipelineName,
          cron,
          env,
          node_name: nodeName || undefined,
          hyperparams,
        },
        { onSuccess: onClose }
      );
    } else {
      createMutation.mutate(
        {
          pipeline_name: pipelineName,
          project_id: projectId,
          cron,
          env,
          node_name: nodeName || undefined,
          hyperparams,
        },
        { onSuccess: onClose }
      );
    }
  };

  return (
    <Modal title={isEdit ? "Edit pipeline schedule" : "Create pipeline schedule"} onClose={onClose} width={480}>
      <div className="projects-modal__form">
        {isEdit ? (
          <>
            <span className="projects-modal__label">Project</span>
            <div className="schedule-form__readonly">{schedule!.project_id ?? "—"}</div>
          </>
        ) : (
          <>
            <label className="projects-modal__label" htmlFor="schedule-project">Project</label>
            <select
              id="schedule-project"
              className="projects-modal__select"
              value={pickedProjectId}
              onChange={(e) => {
                setPickedProjectId(e.target.value);
                setPipelineName("");
              }}
            >
              <option value="">Select a project</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>{project.name ?? project.id}</option>
              ))}
            </select>
          </>
        )}

        <label className="projects-modal__label" htmlFor="schedule-pipeline" style={{ marginTop: 12 }}>Pipeline</label>
        <select
          id="schedule-pipeline"
          className="projects-modal__select"
          value={pipelineName}
          onChange={(e) => setPipelineName(e.target.value)}
          disabled={!projectId}
        >
          <option value="">{projectId ? "Select a pipeline" : "Select a project first"}</option>
          {availablePipelines.map((pipeline) => (
            <option key={pipeline} value={pipeline}>{pipeline}</option>
          ))}
          {/* An edit target may point at a pipeline no longer in the list
              (renamed/removed) — keep it selectable so editing other fields
              doesn't silently clear it. */}
          {isEdit && pipelineName && !availablePipelines.includes(pipelineName) && (
            <option value={pipelineName}>{pipelineName} (not found)</option>
          )}
        </select>

        <span className="projects-modal__label" style={{ marginTop: 12, display: "block" }}>Schedule</span>
        <SchedulePicker cron={cron} onChange={setCron} />

        <label className="projects-modal__label" htmlFor="schedule-environment" style={{ marginTop: 12 }}>Environment</label>
        <select id="schedule-environment" className="projects-modal__select" value={env} onChange={(e) => setEnv(e.target.value)}>
          {environments.map((environment) => (
            <option key={environment} value={environment}>{environment}</option>
          ))}
        </select>

        <button
          type="button"
          className="schedule-form__advanced-toggle"
          onClick={() => setShowAdvanced((v) => !v)}
          aria-expanded={showAdvanced}
        >
          {showAdvanced ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
          Advanced (node, hyperparameters)
        </button>

        {showAdvanced && (
          <>
            <label className="projects-modal__label" htmlFor="schedule-node">Node name (optional)</label>
            <input
              id="schedule-node"
              className="projects-modal__input"
              value={nodeName}
              onChange={(e) => setNodeName(e.target.value)}
              placeholder="Run the whole pipeline if empty"
            />

            <label className="projects-modal__label" htmlFor="schedule-hyperparams" style={{ marginTop: 12 }}>Hyperparameters (optional JSON)</label>
            <textarea
              id="schedule-hyperparams"
              className="projects-modal__input schedule-form__textarea"
              value={hyperparamsText}
              onChange={(e) => setHyperparamsText(e.target.value)}
              placeholder='{"learning_rate": 0.01}'
              rows={4}
              aria-invalid={!!hyperparamsError}
            />
            {hyperparamsError && <p className="projects-modal__hint schedule-form__error">{hyperparamsError}</p>}
          </>
        )}

        <div className="projects-modal__actions" style={{ marginTop: 20 }}>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={handleSubmit} loading={mutation.isPending} disabled={!canSubmit}>
            {mutation.isPending ? (isEdit ? "Saving…" : "Creating…") : isEdit ? "Save changes" : "Schedule Pipeline"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
