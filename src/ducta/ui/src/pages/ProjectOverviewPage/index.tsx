import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { IconArrowRight, IconCircleCheck, IconFolderOff, IconPlus, IconSitemap } from "@tabler/icons-react";
import { useExecutionList, useStaleness } from "../../api/queries";
import type { Problem } from "../../api/queries/problems";
import { useProjectList, useProjectPipelines } from "../../hooks/useProjects";
import { useProjectProblems } from "../../hooks/useProjectProblems";
import { useSourceStore } from "../../store/workspace";
import { Button, EmptyState, PageContainer, PageHeader, Skeleton, StatusBadge } from "../../components/ui";
import { ProjectHealth } from "../../components/Dashboard/ProjectHealth";
import { NewPipelineModal } from "../ProjectPage/NewPipelineModal";
import { routes } from "../../utils/routes";
import { formatRelative } from "../../utils/timeLabels";
import { formatDuration } from "../../utils/formatDuration";
import type { Execution } from "../../types";
import "./ProjectOverviewPage.css";

const FAILED = new Set(["failed", "gate_blocked", "timeout", "cancelled"]);

/** One thing that needs attention, and where to go about it. */
export interface Attention {
  key: string;
  tone: "danger" | "warning";
  text: string;
  to: string;
}

/**
 * What needs attention in a project, most urgent first: configuration errors,
 * pipelines whose latest run failed, and pipelines whose code or inputs changed
 * since their last good run.
 */
export function attentionItems(
  projectId: string,
  problems: Problem[],
  runs: Pick<Execution, "id" | "pipeline_name" | "status" | "started_at">[],
  stale: { node: string; pipeline?: string | null; state: string }[],
): Attention[] {
  const out: Attention[] = [];

  const errors = problems.filter((p) => p.severity === "error");
  if (errors.length > 0) {
    const first = errors[0];
    out.push({
      key: "problems",
      tone: "danger",
      text: errors.length === 1 ? first.message : `${errors.length} configuration errors — ${first.message}`,
      to: first.file ? routes.code(projectId, first.file, first.line ?? undefined) : routes.pipelines(projectId),
    });
  }

  // The latest run of each pipeline (runs come newest first).
  const latest = new Map<string, (typeof runs)[number]>();
  for (const r of runs) if (!latest.has(r.pipeline_name)) latest.set(r.pipeline_name, r);
  for (const r of latest.values()) {
    if (!FAILED.has(String(r.status))) continue;
    out.push({
      key: `run:${r.id}`,
      tone: "danger",
      text: `${r.pipeline_name} ${r.status === "gate_blocked" ? "was blocked by a quality gate" : String(r.status)} ${formatRelative(r.started_at) ?? ""}`.trim(),
      to: routes.run(projectId, r.id),
    });
  }

  const staleByPipeline = new Map<string, number>();
  for (const n of stale) if (n.state === "stale" && n.pipeline) staleByPipeline.set(n.pipeline, (staleByPipeline.get(n.pipeline) ?? 0) + 1);
  for (const [pipeline, count] of staleByPipeline) {
    out.push({
      key: `stale:${pipeline}`,
      tone: "warning",
      text: `${pipeline}: ${count} node${count === 1 ? "" : "s"} changed since the last good run`,
      to: routes.pipeline(projectId, pipeline),
    });
  }
  return out;
}

/**
 * `/p/:projectId` — the project at a glance: what needs attention, how each
 * pipeline is doing, and what ran last. Everything links to where it is dealt with.
 */
export function ProjectOverviewPage() {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { projects, isLoading: projectsLoading } = useProjectList();
  const project = projects.find((p) => p.id === projectId);
  const { pipelines, raw, isLoading: pipelinesLoading } = useProjectPipelines(projectId);
  const activeEnv = useSourceStore((s) => s.activeEnv);
  // The environment the header shows — never a different one in its place.
  const env = activeEnv || "base";

  const { problems } = useProjectProblems(projectId, null);
  const { data: runsData, isLoading: runsLoading } = useExecutionList({ project_id: projectId, limit: 50 });
  const runs: Execution[] = useMemo(() => runsData?.executions ?? [], [runsData]);
  const { data: stale } = useStaleness(projectId, env);
  const attention = useMemo(
    () => attentionItems(projectId, problems, runs, stale ?? []),
    [projectId, problems, runs, stale],
  );
  const [creating, setCreating] = useState(false);

  if (!project) {
    if (projectsLoading) return <PageContainer><Skeleton variant="block" height="200px" /></PageContainer>;
    return (
      <PageContainer>
        <EmptyState
          icon={IconFolderOff}
          title="Project not found"
          description={`There is no project “${projectId}” in this workspace.`}
          action={<Button variant="primary" onClick={() => navigate("/projects")}>All projects</Button>}
        />
      </PageContainer>
    );
  }

  const empty = !pipelinesLoading && pipelines.length === 0;

  return (
    <PageContainer>
      {/* Same width and header as every other page; the description keeps a reading measure. */}
      <PageHeader title={project.name ?? project.id} description={project.description?.trim() || undefined} />

      {empty ? (
        <EmptyState
          icon={IconSitemap}
          title="No pipelines yet"
          description="A pipeline reads datasets, runs your functions on them and writes the results."
          action={
            <Button variant="primary" leftIcon={<IconPlus size={15} />} onClick={() => setCreating(true)}>
              New pipeline
            </Button>
          }
        />
      ) : (
        <>
          <section className="overview-section" aria-labelledby="overview-attention">
            <h2 id="overview-attention" className="overview-h">Needs attention</h2>
            {attention.length === 0 ? (
              <p className="overview-clear">
                <IconCircleCheck size={16} aria-hidden="true" /> Nothing right now — no failed runs, errors or stale pipelines in {env}.
              </p>
            ) : (
              <ul className="overview-list">
                {attention.map((a) => (
                  <li key={a.key}>
                    <Link to={a.to} className={`overview-row tone-${a.tone}`}>
                      <span className="overview-dot" aria-hidden="true" />
                      <span className="overview-row-text">{a.text}</span>
                      <IconArrowRight size={14} className="overview-row-go" aria-hidden="true" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="overview-section" aria-label="Pipelines">
            {/* Every pipeline, run or not: last run, success rate, timing and freshness. */}
            <ProjectHealth projectId={projectId} env={env} />
          </section>

          <section className="overview-section" aria-labelledby="overview-recent">
            <div className="overview-h-row">
              <h2 id="overview-recent" className="overview-h">Recent runs · all environments</h2>
              {runs.length > 0 && <Link to={routes.runs(projectId)} className="overview-more">All runs</Link>}
            </div>
            {runsLoading ? (
              <Skeleton variant="block" height="120px" />
            ) : runs.length === 0 ? (
              <p className="overview-muted">No runs yet. Open a pipeline and run it to see it here.</p>
            ) : (
              <ul className="overview-list">
                {runs.slice(0, 6).map((r) => (
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
        </>
      )}

      {creating && (
        <NewPipelineModal
          projectId={projectId}
          existing={Object.keys(raw?.pipelines ?? {})}
          onClose={() => setCreating(false)}
          onCreated={(name) => {
            setCreating(false);
            navigate(routes.pipeline(projectId, name));
          }}
        />
      )}
    </PageContainer>
  );
}
