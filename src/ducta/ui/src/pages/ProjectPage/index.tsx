import { useParams, useNavigate } from "react-router-dom";
import { useMemo, useState } from "react";
import { useProjectList, useProjectPipelines } from "../../hooks/useProjects";
import { useDeletePipeline } from "../../api/mutations";
import { Button } from "../../components/ui/Button";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { Skeleton } from "../../components/ui/Skeleton";
import { RunPipelineModal } from "../../components/Pipeline/RunPipelineModal";
import { IconFolderOff, IconPlus, IconLayoutGrid, IconSitemap } from "@tabler/icons-react";
import { ProjectDependenciesView } from "./DependenciesMap";
import { NewPipelineModal } from "./NewPipelineModal";
import { PipelinesView, type PipelineSpecLike } from "./PipelinesTable";

export function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { projects, isLoading: projectsLoading } = useProjectList();

  const [showCreate, setShowCreate] = useState(false);
  const [view, setView] = useState<"pipelines" | "dependencies">("dependencies");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [runPipelineId, setRunPipelineId] = useState<string | null>(null);
  const { mutate: deletePipeline, isPending: isDeleting } = useDeletePipeline();

  const { pipelines, raw: serverPipelines } = useProjectPipelines(projectId);
  const pipelineCount = pipelines.length;

  const handleDeletePipeline = () => {
    if (!projectId || !confirmDeleteId) return;
    const pipelineId = confirmDeleteId;
    deletePipeline(
      { projectId, name: pipelineId, expectedSha: serverPipelines?.commit_sha },
      {
        // The mutation invalidates the pipeline list; the row goes when it refetches.
        onSuccess: () => setConfirmDeleteId(null),
      }
    );
  };

  // Find the current project
  const currentProject = useMemo(() => {
    return projects.find((p) => p.id === projectId);
  }, [projects, projectId]);

  if (!currentProject) {
    if (projectsLoading) return <Skeleton variant="block" height="200px" />;
    return (
      <div className="page-error">
        <EmptyState
          icon={IconFolderOff}
          title="Project not found"
          description={`There is no project “${projectId}” in this workspace.`}
          action={
            <Button variant="primary" onClick={() => navigate("/projects")}>
              Back to dashboard
            </Button>
          }
        />
      </div>
    );
  }

  const isMap = view === "dependencies" && Boolean(projectId);

  return (
    <div className={`page-transition project-page${isMap ? " project-page--map" : ""}`}>
      {/* The only chrome either view keeps: how many pipelines, how you look at
          them, and the one action that creates something. MainLayout already
          renders the trail (Projects > this project) right above this bar. */}
      <div className="project-header">
        <span className="project-header-count">
          {pipelineCount} pipeline{pipelineCount !== 1 ? "s" : ""}
        </span>

        <div className="header-actions">
          <div className="view-switch" role="group" aria-label="Project view">
            <Button
              variant={isMap ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("dependencies")}
              title="Cross-pipeline dependency map (explicit deps + shared datasets)"
            >
              <IconSitemap size={14} />
              Map
            </Button>
            <Button
              variant={!isMap ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("pipelines")}
              title="Pipelines as a list"
            >
              <IconLayoutGrid size={14} />
              List
            </Button>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowCreate(true)}
            leftIcon={<IconPlus size={16} stroke={2} />}
          >
            New pipeline
          </Button>
        </div>
      </div>

      {isMap && <ProjectDependenciesView projectId={projectId!} />}

      {!isMap && (
        <PipelinesView
          projectId={projectId!}
          project={currentProject}
          pipelines={pipelines}
          specs={(serverPipelines?.pipelines ?? {}) as Record<string, PipelineSpecLike | undefined>}
          onOpen={(id) => navigate(`/project/${projectId}/pipeline/${id}`)}
          onRun={setRunPipelineId}
          onDelete={setConfirmDeleteId}
          onCreate={() => setShowCreate(true)}
        />
      )}

      {showCreate && projectId && (
        <NewPipelineModal
          projectId={projectId}
          existing={Object.keys(serverPipelines?.pipelines ?? {})}
          onClose={() => setShowCreate(false)}
          onCreated={(name) => {
            setShowCreate(false);
            navigate(`/project/${projectId}/pipeline/${name}`);
          }}
        />
      )}

      {runPipelineId && projectId && (
        <RunPipelineModal
          projectId={projectId}
          pipelineName={runPipelineId}
          onClose={() => setRunPipelineId(null)}
        />
      )}

      <ConfirmDialog
        open={Boolean(confirmDeleteId)}
        title={`Delete pipeline ${confirmDeleteId ?? ""}?`}
        description="This removes the pipeline from the project."
        tone="danger"
        confirmLabel="Delete pipeline"
        pending={isDeleting}
        onConfirm={handleDeletePipeline}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </div>
  );
}
