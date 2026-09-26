import { useMemo } from "react";
import { Link } from "react-router-dom";
import { IconPackage, IconPlus, IconX } from "@tabler/icons-react";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { StatusBadge } from "../ui/StatusBadge";
import type { ProjectSummary } from "../../types";
import { runTimestamp, type ProjectActivity } from "../../utils/dashboardStats";
import { FAILURE_STATUSES } from "../ui/statusMeta";
import { formatRelative } from "../../utils/timeLabels";

interface ProjectsBoardProps {
  projects: ProjectSummary[];
  activity: Map<string, ProjectActivity>;
  onDelete: (projectId: string) => void;
  onCreate: () => void;
}

/**
 * Every project as a card: its name, how many pipelines it holds, and how its
 * last run went. A thin border at rest, no shadow until it is worth one — the
 * card lifts slightly on hover, and a project whose last run failed carries a
 * quiet accent line so it stands out across a whole grid of them without
 * colouring anything that is not worth a second look. Sorted by whichever
 * project did something most recently, with no control exposed to change that.
 */
export function ProjectsBoard({ projects, activity, onDelete, onCreate }: ProjectsBoardProps) {
  const rows = useMemo(() => {
    const lastRunTime = (id: string) => {
      const lastRun = activity.get(id)?.lastRun;
      return lastRun ? (runTimestamp(lastRun) ?? 0) : 0;
    };
    return [...projects].sort(
      (a, b) => lastRunTime(b.id) - lastRunTime(a.id) || a.name.localeCompare(b.name)
    );
  }, [projects, activity]);

  if (projects.length === 0) {
    return (
      <EmptyState
        icon={IconPackage}
        title="No projects yet"
        description="Create a project to start building pipelines — empty, or from a template with a medallion layout ready to run."
        action={
          <Button variant="primary" onClick={onCreate} leftIcon={<IconPlus size={16} stroke={1.75} />}>
            New project
          </Button>
        }
      />
    );
  }

  return (
    <section className="dash-projects" aria-labelledby="dash-projects-title">
      <h2 id="dash-projects-title" className="dash-section-title">
        Projects
      </h2>
      <ul className="dash-project-grid">
        {rows.map((project) => {
          const pipelineCount = project.pipelineCount ?? 0;
          const lastRun = activity.get(project.id)?.lastRun ?? null;
          const failing = Boolean(lastRun && FAILURE_STATUSES.has(lastRun.status));
          return (
            <li key={project.id} className="dash-project-card" data-health={failing ? "failing" : undefined}>
              <Link to={`/project/${encodeURIComponent(project.id)}`} className="dash-project-card-link">
                <div className="dash-project-card-head">
                  <span className="dash-project-card-name">{project.name}</span>
                  <span className="dash-project-card-count">
                    {pipelineCount} pipeline{pipelineCount === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="dash-project-card-foot">
                  {lastRun ? (
                    <>
                      <StatusBadge status={lastRun.status} size="sm" variant="dot" />
                      {formatRelative(lastRun.started_at ?? lastRun.finished_at)}
                    </>
                  ) : (
                    <span className="dash-stat-empty">No runs yet</span>
                  )}
                </div>
              </Link>
              <button
                type="button"
                className="dash-project-card-delete"
                aria-label={`Delete ${project.name}`}
                onClick={() => onDelete(project.id)}
              >
                <IconX size={14} stroke={1.8} />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
