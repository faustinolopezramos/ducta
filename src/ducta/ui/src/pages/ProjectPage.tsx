import { useParams, useNavigate } from "react-router-dom";
import { useMemo, useState, type FormEvent } from "react";
import { useProjectStore } from "../store/projectStore";
import { selectPresent, type ProjectItem } from "../store/reducer";
import { useServerPipelineHydration } from "../hooks/useServerPipelineHydration";
import { apiErrorMessage, useCreatePipeline, useDeletePipeline } from "../api/mutations";
import {
  useExecutionList,
  useProjectDatasets,
  useProjectDependencies,
  useServerProjectPipelines,
} from "../api/queries";
import { computeLineage, lensEdgeClass } from "../utils/lineage";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { DataTable, type DataTableColumn } from "../components/ui/DataTable";
import { EmptyState } from "../components/ui/EmptyState";
import { Modal } from "../components/ui/Modal";
import { Skeleton } from "../components/ui/Skeleton";
import { StatusBadge } from "../components/ui/StatusBadge";
import { DagCanvas } from "../components/Pipeline/DagCanvas";
import { RunPipelineModal } from "../components/Pipeline/RunPipelineModal";
import { compactDuration, formatGlyph } from "../utils/nodePresentation";
import { dependsOnFromEdges } from "../utils/pipelineChain";
import { FAILURE_STATUSES, activityWindowStart, runTimestamp, type RunLike } from "../utils/dashboardStats";
import { formatRelative } from "../utils/timeLabels";
import { useUIStore } from "../store/uiStore";
import {
  IconFolderOff,
  IconPlus,
  IconTrash,
  IconPlayerPlay,
  IconLayoutGrid,
  IconSitemap,
  IconArrowRight,
} from "@tabler/icons-react";

/** Boundary datasets listed per side before the rest are summarised. */
const MAX_BOUNDARY = 3;

interface DatasetRef {
  name: string;
  format: string | null;
  layer: "bronze" | "silver" | "gold" | null;
}

/** One side of a pipeline's data boundary, as read off its supernode card. */
function BoundaryList({ label, refs }: { label: string; refs: DatasetRef[] }) {
  if (refs.length === 0) return null;
  const shown = refs.slice(0, MAX_BOUNDARY);
  const rest = refs.length - shown.length;
  return (
    <div className="supernode-boundary-side">
      <span className="supernode-boundary-label">{label}</span>
      {shown.map((ref) => (
        <span key={ref.name} className="supernode-dataset" data-layer={ref.layer ?? undefined}>
          <span className="supernode-swatch" aria-hidden="true" />
          <span className="supernode-dataset-glyph" aria-hidden="true">
            {formatGlyph(ref.format)}
          </span>
          <span className="supernode-dataset-name">{ref.name}</span>
        </span>
      ))}
      {rest > 0 && <span className="supernode-more">+{rest} more</span>}
    </div>
  );
}

/**
 * Project map: the pipelines of a project as supernodes, edges labelled with
 * the datasets they share.
 *
 * The pipelines are the subject of this screen, so they get the whole window
 * and the whole click: a card opens its pipeline, no small target inside it to
 * hit. The dependency lens — which pipelines feed this one, which consume it —
 * follows hover and focus instead of costing a click, which leaves the single
 * click free for the one thing you actually come here to do.
 */
function ProjectDependenciesView({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const { data, isLoading, isError } = useProjectDependencies(projectId);
  const { data: pipelinesData } = useServerProjectPipelines(projectId);
  const { data: datasetsData } = useProjectDatasets(projectId);
  /** Pipeline under the cursor or keyboard focus — drives the lens, not selection. */
  const [focused, setFocused] = useState<string | null>(null);
  /** The same layer direction the viewer chose on the pipeline canvas. */
  const orientation = useUIStore((s) => s.pipelineOrientation);

  const { items, labels, parents } = useMemo(() => {
    const pipelines = Object.keys(data?.pipelines ?? {});
    const dependsOn = dependsOnFromEdges(pipelines, data?.edges ?? []);
    const edgeDatasets = new Map<string, Set<string>>();
    for (const edge of data?.edges ?? []) {
      if (edge.from_pipeline === edge.to_pipeline) continue;
      const key = `${edge.from_pipeline}->${edge.to_pipeline}`;
      if (!edgeDatasets.has(key)) edgeDatasets.set(key, new Set());
      if (edge.dataset) edgeDatasets.get(key)!.add(edge.dataset);
    }
    const labels = new Map<string, string>();
    for (const [key, datasets] of edgeDatasets) {
      const list = [...datasets];
      if (list.length > 0) {
        labels.set(key, list.length > 2 ? `${list.slice(0, 2).join(", ")} +${list.length - 2}` : list.join(", "));
      }
    }
    return {
      items: pipelines.map((p) => ({
        id: p,
        dependsOn: [...(dependsOn.get(p) ?? [])],
        nodeCount: (data?.pipelines?.[p] ?? []).length,
        nodes: data?.pipelines?.[p] ?? [],
      })),
      labels,
      parents: new Map(pipelines.map((p) => [p, [...(dependsOn.get(p) ?? [])]])),
    };
  }, [data]);

  /**
   * Each pipeline's interface with the rest of the project: the datasets it
   * consumes from outside itself, and the ones it publishes for others.
   *
   * This is what a pipeline *is* at project altitude. The card used to list up
   * to six truncated node names instead, which says nothing about how the
   * pipelines fit together.
   */
  const boundary = useMemo(() => {
    const result = new Map<string, { consumes: DatasetRef[]; publishes: DatasetRef[] }>();
    for (const d of datasetsData?.datasets ?? []) {
      const producerPipelines = new Set(
        d.producers.map((p) => p.pipeline).filter(Boolean) as string[]
      );
      const consumerPipelines = new Set(
        d.consumers.map((c) => c.pipeline).filter(Boolean) as string[]
      );
      const ref: DatasetRef = { name: d.name, format: d.format ?? null, layer: d.layer ?? null };

      for (const pipeline of consumerPipelines) {
        // Read from outside this pipeline: nobody inside it writes the dataset.
        if (producerPipelines.has(pipeline)) continue;
        const entry = result.get(pipeline) ?? { consumes: [], publishes: [] };
        entry.consumes.push(ref);
        result.set(pipeline, entry);
      }
      for (const pipeline of producerPipelines) {
        // Published: somebody outside this pipeline reads it, or nobody does
        // (a terminal output is still this pipeline's product).
        const readElsewhere = [...consumerPipelines].some((c) => c !== pipeline);
        if (consumerPipelines.size > 0 && !readElsewhere) continue;
        const entry = result.get(pipeline) ?? { consumes: [], publishes: [] };
        entry.publishes.push(ref);
        result.set(pipeline, entry);
      }
    }
    return result;
  }, [datasetsData]);

  const lineage = useMemo(() => computeLineage(focused, parents), [focused, parents]);

  const open = (pipelineId: string) => navigate(`/project/${projectId}/pipeline/${pipelineId}`);

  if (isLoading) {
    return (
      <div className="project-map project-map--placeholder">
        <Skeleton variant="block" height="100%" />
      </div>
    );
  }
  if (isError) {
    return (
      <div className="project-map project-map--placeholder">
        <EmptyState
          icon={IconSitemap}
          title="Couldn't load the project map"
          description="Check that the API is reachable and try again."
        />
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="project-map project-map--placeholder">
        <EmptyState icon={IconSitemap} title="No pipelines in this project yet" />
      </div>
    );
  }

  const hasCrossEdges = labels.size > 0 || items.some((i) => i.dependsOn.length > 0);

  return (
    <div className="project-map">
      <DagCanvas
        items={items}
        orientation={orientation}
        edgeLabel={(from, to) => labels.get(`${from}->${to}`) ?? null}
        edgeClassName={(from, to) => lensEdgeClass(lineage, from, to)}
        renderItem={(item) => {
          const pipelineType = pipelinesData?.pipelines?.[item.id]?.type ?? "batch";
          const lensDir = lineage
            ? lineage.upstream.has(item.id) ? "up"
            : lineage.downstream.has(item.id) ? "down"
            : null
            : null;
          const lensDepth =
            lensDir === "up"
              ? lineage!.upstream.get(item.id)
              : lineage?.downstream.get(item.id);
          const isFocused = focused === item.id;
          const dimmed = lineage ? !isFocused && !lensDir : false;
          const edges = boundary.get(item.id);
          return (
            <div
              role="button"
              tabIndex={0}
              aria-label={`Open pipeline ${item.id}, ${item.nodeCount} nodes`}
              className={`pipeline-supernode ${isFocused ? "focused" : ""} ${dimmed ? "dag-dimmed" : ""} ${lensDir ? `lens-${lensDir}` : ""}`}
              onClick={() => open(item.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  open(item.id);
                }
              }}
              onMouseEnter={() => setFocused(item.id)}
              onMouseLeave={() => setFocused((cur) => (cur === item.id ? null : cur))}
              onFocus={() => setFocused(item.id)}
              onBlur={() => setFocused((cur) => (cur === item.id ? null : cur))}
            >
              {lensDir && lensDepth != null && (
                <span className={`lens-tag lens-tag-${lensDir}`}>
                  {lensDir === "up" ? "\u2191" : "\u2193"}{lensDepth}
                </span>
              )}
              <div className="supernode-head">
                <span className="supernode-name">{item.id}</span>
                <IconArrowRight className="supernode-go" size={16} stroke={2} />
              </div>
              <div className="supernode-meta">
                <span className="supernode-type">{pipelineType}</span>
                <span className="supernode-count">
                  {item.nodeCount} node{item.nodeCount !== 1 ? "s" : ""}
                </span>
              </div>
              {edges && (edges.consumes.length > 0 || edges.publishes.length > 0) && (
                <div className="supernode-boundary">
                  <BoundaryList label="Consumes" refs={edges.consumes} />
                  <BoundaryList label="Publishes" refs={edges.publishes} />
                </div>
              )}
            </div>
          );
        }}
      />
      {!hasCrossEdges && (
        <p className="project-map-hint">
          No cross-pipeline dependencies detected — pipelines neither declare dependencies on each
          other's nodes nor consume each other's output datasets.
        </p>
      )}
    </div>
  );
}

export function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const outerState = useProjectStore();
  const state = selectPresent(outerState);
  const dispatch = useProjectStore(s => s.dispatch);
  const projects = state.projects;

  const [showCreate, setShowCreate] = useState(false);
  const [view, setView] = useState<"pipelines" | "dependencies">("dependencies");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [runPipelineId, setRunPipelineId] = useState<string | null>(null);
  const { mutate: deletePipeline, isPending: isDeleting } = useDeletePipeline();

  // Load pipelines from server when projectId changes
  useServerPipelineHydration(projectId, dispatch);

  // Server pipeline listing — the authoritative count for server-backed projects,
  // whose client-store `pipelines` only hydrates on the pipeline page (that gap
  // is why the header used to read "0 Pipelines" while the map showed all of them).
  const { data: serverPipelines } = useServerProjectPipelines(projectId ?? "");
  const pipelineCount = Math.max(
    Object.keys(serverPipelines?.pipelines ?? {}).length,
    projects.find((p) => p.id === projectId)?.pipelines.length ?? 0
  );

  const handleDeletePipeline = () => {
    if (!projectId || !confirmDeleteId) return;
    const pipelineId = confirmDeleteId;
    deletePipeline(
      { projectId, name: pipelineId, expectedSha: serverPipelines?.commit_sha },
      {
        onSuccess: () => {
          dispatch({ type: "DELETE_PIPELINE", payload: pipelineId });
          setConfirmDeleteId(null);
        },
      }
    );
  };

  // Find the current project
  const currentProject = useMemo(() => {
    return projects.find((p) => p.id === projectId);
  }, [projects, projectId]);

  if (!currentProject) {
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
          pipelineCount={pipelineCount}
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
            // Select the project so ADD_PIPELINE targets the right one
            dispatch({ type: "SELECT_PROJECT", payload: projectId });
            dispatch({
              type: "ADD_PIPELINE",
              payload: {
                id: name,
                name,
                nodes: [],
                active: true,
                createdAt: Date.now(),
                updatedAt: Date.now(),
              },
            });
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

interface PipelineSpecLike {
  type?: string;
  description?: string;
}

interface PipelineRow {
  id: string;
  name: string;
  type: string;
  description?: string;
  nodes: number;
  lastRun: RunLike | null;
  runsThisWeek: number;
}

/**
 * A project's pipelines as a table: what each one is, how big, and how its
 * last run went. It replaces a grid of identical cards whose run and delete
 * buttons stayed invisible until hover, and whose delete asked "Yes / No" in an
 * overlay on top of the card it was deleting.
 */
function PipelinesView({
  projectId,
  project,
  pipelineCount,
  specs,
  onOpen,
  onRun,
  onDelete,
  onCreate,
}: {
  projectId: string;
  project: ProjectItem;
  pipelineCount: number;
  specs: Record<string, PipelineSpecLike | undefined>;
  onOpen: (pipelineId: string) => void;
  onRun: (pipelineId: string) => void;
  onDelete: (pipelineId: string) => void;
  onCreate: () => void;
}) {
  // Fixed for the life of the view so the query key does not change every render.
  const [since] = useState(activityWindowStart);
  const { data: runsData, isLoading } = useExecutionList({ project_id: projectId, since, limit: 200 });

  const rows = useMemo<PipelineRow[]>(() => {
    const runs = ((runsData?.executions ?? []) as RunLike[])
      .map((run) => ({ run, t: runTimestamp(run) ?? 0 }))
      .sort((a, b) => b.t - a.t);
    return project.pipelines.map((pipeline) => {
      const spec = specs[pipeline.id];
      const own = runs.filter((x) => x.run.pipeline_name === pipeline.id);
      return {
        id: pipeline.id,
        name: pipeline.name || pipeline.id,
        type: spec?.type ?? (pipeline as { type?: string }).type ?? "batch",
        description: spec?.description ?? (pipeline as { description?: string }).description,
        nodes: pipeline.nodes.length,
        lastRun: own[0]?.run ?? null,
        runsThisWeek: own.length,
      };
    });
  }, [runsData, project.pipelines, specs]);

  const columns: DataTableColumn<PipelineRow>[] = [
    {
      key: "name",
      header: "Pipeline",
      cell: (r) => (
        <span className="dash-table-project">
          <span className="project-list-name">{r.name}</span>
          {r.description && <span className="project-list-desc">{r.description}</span>}
        </span>
      ),
    },
    {
      key: "type",
      header: "Type",
      width: "110px",
      cell: (r) => <span className="pipeline-type-tag">{r.type}</span>,
    },
    { key: "nodes", header: "Nodes", align: "right", mono: true, width: "80px", cell: (r) => r.nodes },
    {
      key: "last",
      header: "Last run",
      width: "230px",
      cell: (r) =>
        r.lastRun ? (
          <span className="dash-table-last">
            <StatusBadge
              status={r.lastRun.status}
              label={r.lastRun.status === "gate_blocked" ? "Gate blocked" : undefined}
              size="sm"
            />
            <span>
              {formatRelative(r.lastRun.started_at ?? r.lastRun.finished_at)}
              {r.lastRun.duration_seconds != null ? ` · ${compactDuration(r.lastRun.duration_seconds)}` : ""}
            </span>
          </span>
        ) : (
          <span className="dash-muted">{isLoading ? "…" : "No runs this week"}</span>
        ),
    },
    { key: "runs", header: "Runs · 7 d", align: "right", mono: true, width: "96px", cell: (r) => r.runsThisWeek },
    {
      key: "actions",
      header: "",
      headerLabel: "Actions",
      align: "right",
      width: "96px",
      cell: (r) => (
        <span className="project-list-actions">
          <button
            type="button"
            className="dash-menu-trigger"
            aria-label={`Run ${r.name}`}
            title="Run pipeline"
            onClick={(e) => {
              e.stopPropagation();
              onRun(r.id);
            }}
          >
            <IconPlayerPlay size={15} stroke={1.75} />
          </button>
          <button
            type="button"
            className="dash-menu-trigger project-list-delete"
            aria-label={`Delete ${r.name}`}
            title="Delete pipeline"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(r.id);
            }}
          >
            <IconTrash size={15} stroke={1.75} />
          </button>
        </span>
      ),
    },
  ];

  return (
    <div className="project-content project-list t-container">
      <header className="project-list-head">
        <h1 className="project-list-title">{project.name}</h1>
        <p className="project-list-meta">
          <span className="project-list-id">{project.id}</span> · {pipelineCount} pipeline
          {pipelineCount !== 1 ? "s" : ""}
        </p>
      </header>

      {project.pipelines.length === 0 ? (
        <EmptyState
          icon={IconSitemap}
          title="No pipelines yet"
          description="Create a pipeline, then add nodes to it on the canvas."
          action={
            <Button variant="primary" onClick={onCreate} leftIcon={<IconPlus size={16} stroke={2} />}>
              New pipeline
            </Button>
          }
        />
      ) : (
        <DataTable<PipelineRow>
          columns={columns}
          rows={rows}
          rowKey={(r) => r.id}
          onRowClick={(r) => onOpen(r.id)}
          rowClassName={(r) =>
            r.lastRun && FAILURE_STATUSES.has(r.lastRun.status) ? "dash-row--failing" : undefined
          }
          minWidth={760}
          caption={`Pipelines of ${project.name}`}
        />
      )}
    </div>
  );
}

/** Pipeline names become YAML keys and URL segments; dots are the layer convention. */
const PIPELINE_NAME_RE = /^[a-zA-Z][a-zA-Z0-9_.-]*$/;

/**
 * Creating a pipeline, as a form: Enter submits, the name is checked before it
 * is sent (including against the pipelines that already exist), and a refusal
 * is shown in the dialog. It used to be an inline card that only appeared in
 * the list view, so asking for a pipeline from the map first switched views.
 */
function NewPipelineModal({
  projectId,
  existing,
  onClose,
  onCreated,
}: {
  projectId: string;
  existing: string[];
  onClose: () => void;
  onCreated: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { mutate: createPipeline, isPending } = useCreatePipeline();

  const trimmed = name.trim();
  const problem = !trimmed
    ? null
    : !PIPELINE_NAME_RE.test(trimmed)
      ? "Start with a letter, then use only letters, digits, _, - or ."
      : existing.includes(trimmed)
        ? `A pipeline named “${trimmed}” already exists in this project.`
        : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!trimmed || problem || isPending) return;
    setError(null);
    createPipeline(
      { projectId, name: trimmed, spec: { nodes: [], type: "batch", active: true } },
      {
        onSuccess: () => onCreated(trimmed),
        onError: (err: unknown) => setError(apiErrorMessage(err, "Couldn’t create the pipeline. Try again.")),
      }
    );
  };

  return (
    <Modal title="New pipeline" onClose={onClose}>
      <form className="projects-modal__form" onSubmit={submit} noValidate>
        <label className="projects-modal__label" htmlFor="new-pipeline-name">
          Pipeline name
        </label>
        <input
          id="new-pipeline-name"
          className="projects-modal__input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="silver.clean"
          autoComplete="off"
          aria-invalid={Boolean(problem)}
          aria-describedby="new-pipeline-name-hint"
        />
        <p id="new-pipeline-name-hint" className={`projects-modal__hint${problem ? " dash-hint-error" : ""}`}>
          {problem ?? "Starts as an empty batch pipeline; add nodes on the canvas."}
        </p>
        {error && (
          <p className="dash-form-error" role="alert">
            {error}
          </p>
        )}
        <div className="projects-modal__actions">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={isPending} disabled={!trimmed || Boolean(problem)}>
            Create pipeline
          </Button>
        </div>
      </form>
    </Modal>
  );
}
