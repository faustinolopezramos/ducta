import { useCallback, useMemo, useState } from "react";
import { IconPlus } from "@tabler/icons-react";
import { useDeleteServerProject, useExecutionList } from "../api/queries";
import { useSchedules } from "../api/schedulesApi";
import { toastStore } from "../hooks/useModalStack";
import { usePermission } from "../hooks/usePermission";
import { Button, ConfirmDialog, PageContainer, PageHeader } from "./ui";
import type { ProjectSummary } from "../types";
import { activityWindowStart, nextScheduledRun, summarizeRuns, type RunLike } from "../utils/dashboardStats";
import { OpsSummary } from "./Dashboard/OpsSummary";
import { RunsPanel } from "./Dashboard/RunsPanel";
import { ProjectsBoard } from "./Dashboard/ProjectsBoard";
import { NewProjectModal } from "./Dashboard/NewProjectModal";

interface ProjectsListProps {
  projects: ProjectSummary[];
  workspacePath?: string;
}

/**
 * The dashboard: the workspace at a glance, then what needs attention, then
 * every project with what it has been doing.
 *
 * It used to be a grid of project cards that said how many pipelines each had
 * and when it was created — nothing about whether anything was running, broken
 * or about to run, though every one of those answers was one request away.
 */
export function ProjectsList({ projects, workspacePath }: ProjectsListProps) {
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const deleteProject = useDeleteServerProject();

  // Fixed for the life of the page so the query key does not change every render.
  const [since] = useState(activityWindowStart);
  const { data: runsData, isLoading: runsLoading } = useExecutionList({ since, limit: 500 });
  const { data: schedulesData } = useSchedules();

  const stats = useMemo(
    () => summarizeRuns((runsData?.executions ?? []) as RunLike[]),
    [runsData]
  );
  const next = nextScheduledRun(schedulesData?.schedules ?? []);

  const names = useMemo(() => new Map(projects.map((p) => [p.id, p.name])), [projects]);
  const projectName = useCallback(
    (id: string | null | undefined) => (id ? (names.get(id) ?? id) : null),
    [names]
  );

  const projectToDelete = projects.find((project) => project.id === confirmDelete);

  // Creating and deleting projects needs project.write; a viewer sees the board only.
  const canWrite = usePermission("project.write");

  const handleDelete = () => {
    if (!projectToDelete) return;
    deleteProject.mutate(
      { projectId: projectToDelete.id, force: true },
      {
        // The mutation invalidates the project list; the card goes when it refetches.
        onSuccess: () => {
          toastStore.getState().show(`Project "${projectToDelete.name}" deleted`, "success");
          setConfirmDelete(null);
        },
        onError: () =>
          toastStore.getState().show("Unable to delete the project. Check its permissions and try again.", "error"),
      }
    );
  };

  return (
    <PageContainer className="dashboard-page">
      <PageHeader
        title="Dashboard"
        description={
          workspacePath
            ? `Workspace: ${workspacePath}`
            : "What is running, what needs attention, and every project in this workspace."
        }
        actions={
          canWrite && (
            <Button
              variant="primary"
              onClick={() => setNewProjectOpen(true)}
              leftIcon={<IconPlus size={16} stroke={1.75} />}
            >
              New project
            </Button>
          )
        }
      />

      <div className="dash-stack">
        <OpsSummary
          activeCount={stats.active.length}
          failedLast24h={stats.failedLast24h}
          next={next}
          loading={runsLoading}
        />

        <RunsPanel
          active={stats.active}
          attention={stats.attention}
          projectName={projectName}
          loading={runsLoading}
        />

        <ProjectsBoard
          projects={projects}
          activity={stats.byProject}
          onDelete={canWrite ? setConfirmDelete : undefined}
          onCreate={canWrite ? () => setNewProjectOpen(true) : undefined}
        />
      </div>

      {newProjectOpen && (
        <NewProjectModal
          onClose={() => setNewProjectOpen(false)}
          onCreated={(id) => {
            toastStore.getState().show(`Project "${id}" created`, "success");
            setNewProjectOpen(false);
          }}
        />
      )}

      <ConfirmDialog
        open={!!confirmDelete}
        title={`Delete ${projectToDelete?.name}?`}
        description="This permanently deletes the project and all its pipelines."
        tone="danger"
        requireTyping={projectToDelete?.name}
        confirmLabel="Delete project"
        pending={deleteProject.isPending}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </PageContainer>
  );
}
