import { useParams, useNavigate, Link } from "react-router-dom";
import { useMemo, useState } from "react";
import { useProjectList, useProjectPipelines } from "../../hooks/useProjects";
import { useDeletePipeline } from "../../api/mutations";
import { Button } from "../../components/ui/Button";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { Skeleton } from "../../components/ui/Skeleton";
import { RunPipelineModal } from "../../components/Pipeline/RunPipelineModal";
import {
  IconFolderOff,
  IconPlus,
  IconList,
  IconSitemap,
  IconActivity,
  IconAlertCircle,
  IconArrowRight,
} from "@tabler/icons-react";
import { ProjectDependenciesView } from "./DependenciesMap";
import { NewPipelineModal } from "./NewPipelineModal";
import { PipelinesView, type PipelineSpecLike } from "./PipelinesTable";
import { routes } from "../../utils/routes";
import { useProjectProblems } from "../../hooks/useProjectProblems";
import { useApplyFix } from "../../hooks/useApplyFix";
import { ProjectConfigErrors } from "../../components/Problems/ProjectConfigErrors";
import { attentionItems } from "../ProjectOverviewPage";
import { useExecutionList, useStaleness } from "../../api/queries";
import { useSourceStore } from "../../store/workspace";
import { ProjectHealth } from "../../components/Dashboard/ProjectHealth";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { formatDuration } from "../../utils/formatDuration";
import { formatRelative } from "../../utils/timeLabels";
import type { Execution } from "../../types";
import "../ProjectOverviewPage/ProjectOverviewPage.css";

export function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { projects, isLoading: projectsLoading } = useProjectList();

  const [showCreate, setShowCreate] = useState(false);
  const [view, setView] = useState<"pipelines" | "dependencies" | "health">("dependencies");
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

  if (currentProject.configError) {
    return <BrokenProject projectId={projectId ?? ""} />;
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
              aria-pressed={isMap}
              title="Cross-pipeline dependency map (explicit deps + shared datasets)"
              leftIcon={<IconSitemap size={14} />}
            >
              Map
            </Button>
            <Button
              variant={view === "pipelines" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("pipelines")}
              aria-pressed={view === "pipelines"}
              title="Pipelines as a list"
              leftIcon={<IconList size={14} />}
            >
              List
            </Button>
            <Button
              variant={view === "health" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("health")}
              aria-pressed={view === "health"}
              title="Pipeline health, SLA and recent runs"
              leftIcon={<IconActivity size={14} />}
            >
              Health
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

      {!isMap && <ProjectAttentionStrip projectId={projectId!} />}

      {isMap && <ProjectDependenciesView projectId={projectId!} />}

      {view === "pipelines" && (
        <PipelinesView
          projectId={projectId!}
          project={currentProject}
          pipelines={pipelines}
          specs={(serverPipelines?.pipelines ?? {}) as Record<string, PipelineSpecLike | undefined>}
          onOpen={(id) => navigate(routes.pipeline(projectId!, id))}
          onRun={setRunPipelineId}
          onDelete={setConfirmDeleteId}
          onCreate={() => setShowCreate(true)}
        />
      )}

      {view === "health" && <ProjectHealthPane projectId={projectId!} />}

      {showCreate && projectId && (
        <NewPipelineModal
          projectId={projectId}
          existing={Object.keys(serverPipelines?.pipelines ?? {})}
          onClose={() => setShowCreate(false)}
          onCreated={(name) => {
            setShowCreate(false);
            navigate(routes.pipeline(projectId!, name));
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


/** The project's configuration does not load: its problems, each a way to the line. */
function BrokenProject({ projectId }: { projectId: string }) {
  const { problems, isChecking } = useProjectProblems(projectId, null);
  const applyFix = useApplyFix();
  return (
    <ProjectConfigErrors
      projectId={projectId}
      problems={problems}
      isChecking={isChecking}
      onFix={(p) => void applyFix(projectId, p).catch(() => undefined)}
    />
  );
}

function ProjectAttentionStrip({ projectId }: { projectId: string }) {
  const activeEnv = useSourceStore((s) => s.activeEnv);
  const env = activeEnv || "base";
  const { problems } = useProjectProblems(projectId, null);
  const { data: runsData } = useExecutionList({ project_id: projectId, limit: 50 });
  const runs = useMemo(() => (runsData?.executions ?? []) as Execution[], [runsData]);
  const { data: stale } = useStaleness(projectId, env);
  const attention = useMemo(
    () => attentionItems(projectId, problems, runs, stale ?? []),
    [projectId, problems, runs, stale],
  );

  if (attention.length === 0) return null;

  return (
    <aside className="project-attention-banner" aria-label="Project issues needing attention">
      <span className="project-attention-title">
        <IconAlertCircle size={15} /> Needs attention ({attention.length}):
      </span>
      <div className="project-attention-links">
        {attention.slice(0, 3).map((a) => (
          <Link key={a.key} to={a.to} className={`project-attention-link tone-${a.tone}`}>
            <span className="overview-dot" aria-hidden="true" />
            <span>{a.text}</span>
            <IconArrowRight size={13} aria-hidden="true" />
          </Link>
        ))}
      </div>
    </aside>
  );
}

function ProjectHealthPane({ projectId }: { projectId: string }) {
  const activeEnv = useSourceStore((s) => s.activeEnv);
  const env = activeEnv || "base";
  const { data: runsData, isLoading: runsLoading } = useExecutionList({ project_id: projectId, limit: 50 });
  const runs = useMemo(() => (runsData?.executions ?? []) as Execution[], [runsData]);

  return (
    <div className="project-health-pane">
      <ProjectHealth projectId={projectId} env={env} />
      <section className="overview-section" style={{ marginTop: "var(--space-6, 24px)" }}>
        <div className="overview-h-row">
          <h2 className="overview-h">Recent runs · all environments</h2>
          {runs.length > 0 && <Link to={routes.runs(projectId)} className="overview-more">All runs</Link>}
        </div>
        {runsLoading ? (
          <Skeleton variant="block" height="120px" />
        ) : runs.length === 0 ? (
          <p className="overview-muted">No runs yet. Open a pipeline and run it to see it here.</p>
        ) : (
          <ul className="overview-list">
            {runs.slice(0, 8).map((r) => (
              <li key={r.id}>
                <Link to={routes.run(projectId, r.id)} className="overview-row">
                  <StatusBadge status={r.status} size="sm" variant="dot" />
                  <span className="overview-row-text mono">{r.pipeline_name}</span>
                  <span className="overview-muted">{r.env}</span>
                  <span className="overview-muted overview-num">
                    {r.duration_seconds != null ? formatDuration(r.duration_seconds) : ""}
                  </span>
                  <span className="overview-muted overview-when">{formatRelative(r.started_at) ?? ""}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
