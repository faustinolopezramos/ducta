import { useParams, useNavigate, Link } from "react-router-dom";
import { useMemo, useState, useRef, useEffect } from "react";
import { useProjectStore } from "../store/projectStore";
import { selectPresent } from "../store/reducer";
import { useServerPipelineHydration } from "../hooks/useServerPipelineHydration";
import { useCreatePipeline, useDeletePipeline } from "../api/mutations";
import {
  useProjectDatasets,
  useProjectDependencies,
  useServerProjectPipelines,
} from "../api/queries";
import { computeLineage, lensEdgeClass } from "../utils/lineage";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { DagCanvas } from "../components/Pipeline/DagCanvas";
import { RunPipelineModal } from "../components/Pipeline/RunPipelineModal";
import { formatGlyph } from "../utils/nodePresentation";
import {
  IconChevronRight,
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
          <span className="supernode-dataset-glyph" aria-hidden="true">
            {formatGlyph(ref.format)}
          </span>
          {ref.name}
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

  const { items, labels, parents } = useMemo(() => {
    const pipelines = Object.keys(data?.pipelines ?? {});
    const dependsOn = new Map<string, Set<string>>(pipelines.map((p) => [p, new Set<string>()]));
    const edgeDatasets = new Map<string, Set<string>>();
    for (const edge of data?.edges ?? []) {
      if (edge.from_pipeline === edge.to_pipeline) continue;
      dependsOn.get(edge.to_pipeline)?.add(edge.from_pipeline);
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
  const [createName, setCreateName] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [runPipelineId, setRunPipelineId] = useState<string | null>(null);
  const createInputRef = useRef<HTMLInputElement>(null);
  const { mutate: createPipeline, isPending: isCreating } = useCreatePipeline();
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

  // Auto-focus the name input when the create form opens
  useEffect(() => {
    if (showCreate) createInputRef.current?.focus();
  }, [showCreate]);

  const handleOpenCreate = () => {
    setCreateName("");
    // The form lives in the list view, so asking for a pipeline goes there.
    setView("pipelines");
    setShowCreate(true);
  };

  const handleCreate = () => {
    const name = createName.trim();
    if (!name || !projectId) return;
    createPipeline(
      { projectId, name, spec: { nodes: [], type: "batch", active: true } },
      {
        onSuccess: () => {
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
        },
      }
    );
  };

  const handleDeletePipeline = (pipelineId: string) => {
    if (!projectId) return;
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
        <div className="error-content">
          <div className="error-icon">🔍</div>
          <h1 className="t-h2">Project not found</h1>
          <p className="t-p">The project "{projectId}" does not exist.</p>
          <Button variant="primary" onClick={() => navigate("/projects")}>Back to Projects</Button>
        </div>
      </div>
    );
  }

  const isMap = view === "dependencies" && Boolean(projectId);

  return (
    <div className={`page-transition project-page${isMap ? " project-page--map" : ""}`}>
      {/* The only chrome the map keeps: where you are, how you look at it, and
          the one action that creates something. Everything else the page used
          to stack above the canvas (title, id, pipeline count, section
          heading) repeated what the breadcrumb and the cards already say, and
          it was costing the map most of its height. */}
      <div className="project-header">
        {/* MainLayout already renders the trail (Projects > this project) right
            above this bar, so in map view the left slot drops the duplicate and
            keeps only what the trail does not say. */}
        {isMap ? (
          <span className="project-header-count">
            {pipelineCount} pipeline{pipelineCount !== 1 ? "s" : ""}
          </span>
        ) : (
          <div className="breadcrumbs">
            <Link to="/projects" className="breadcrumb-item">Projects</Link>
            <IconChevronRight size={14} className="separator" />
            <span className="breadcrumb-current">{currentProject.name}</span>
          </div>
        )}

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
          <Button variant="primary" size="sm" onClick={handleOpenCreate}>
            <IconPlus size={16} stroke={2} />
            <span>New Pipeline</span>
          </Button>
        </div>
      </div>

      {isMap && <ProjectDependenciesView projectId={projectId!} />}

      {!isMap && (
      <div className="project-content t-container">
        <section className="project-intro">
          <h1 className="t-h1">{currentProject.name}</h1>
          <div className="project-meta">
            <span className="project-id">{currentProject.id}</span>
            <span className="dot-separator">•</span>
            <span className="project-stats-info">{pipelineCount} Pipeline{pipelineCount !== 1 ? "s" : ""}</span>
          </div>
        </section>

        {/* Pipelines List */}
        <section className="pipelines-section">
          {/* Inline create form */}
          {showCreate && (
            <div className="create-pipeline-card t-card">
              <div className="form-title">Create New Pipeline</div>
              <input
                ref={createInputRef}
                className="t-input"
                value={createName}
                onChange={e => setCreateName(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter") handleCreate();
                  if (e.key === "Escape") { setShowCreate(false); setCreateName(""); }
                }}
                placeholder="e.g. data_ingestion_daily"
              />
              <div className="form-actions">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleCreate}
                  disabled={isCreating || !createName.trim()}
                >
                  {isCreating ? "Creating…" : "Create"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => { setShowCreate(false); setCreateName(""); }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {currentProject.pipelines.length === 0 && !showCreate ? (
            <div className="empty-state t-card">
              <div className="empty-icon">⚙️</div>
              <h3 className="empty-title">No pipelines yet</h3>
              <p className="empty-desc">Create your first pipeline to get started with data orchestration.</p>
              <Button variant="primary" onClick={handleOpenCreate}>Create Pipeline</Button>
            </div>
          ) : (
            <div className="pipelines-grid">
              {currentProject.pipelines.map((pipeline) => (
                <div
                  key={pipeline.id}
                  className={`pipeline-card t-card ${confirmDeleteId === pipeline.id ? "deleting" : ""}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/project/${projectId}/pipeline/${pipeline.id}`)}
                  onKeyDown={(e) => {
                    // The card holds its own buttons (delete, confirm), so it
                    // cannot itself be a <button>; give it button semantics
                    // and the two keys a button would answer to.
                    if (e.target !== e.currentTarget) return;
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      navigate(`/project/${projectId}/pipeline/${pipeline.id}`);
                    }
                  }}
                >
                  <div className="card-header">
                    <div className="pipeline-icon">
                      <IconLayoutGrid size={18} stroke={1.5} />
                    </div>
                    <div className="pipeline-title-group">
                      <h3 className="pipeline-title">{pipeline.name || pipeline.id}</h3>
                      <p className="pipeline-id-sub">{pipeline.id}</p>
                    </div>

                    <button
                      className="run-btn"
                      title="Run pipeline"
                      onClick={(e) => {
                        e.stopPropagation();
                        setRunPipelineId(pipeline.id);
                      }}
                    >
                      <IconPlayerPlay size={16} />
                    </button>

                    <button
                      className="delete-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmDeleteId(confirmDeleteId === pipeline.id ? null : pipeline.id);
                      }}
                    >
                      <IconTrash size={16} />
                    </button>
                  </div>

                  {confirmDeleteId === pipeline.id && (
                    <div className="delete-confirm-overlay" role="presentation" onClick={e => e.stopPropagation()}>
                      <p>Delete this pipeline?</p>
                      <div className="confirm-actions">
                        <button className="confirm-yes" onClick={() => handleDeletePipeline(pipeline.id)} disabled={isDeleting}>Yes</button>
                        <button className="confirm-no" onClick={() => setConfirmDeleteId(null)}>No</button>
                      </div>
                    </div>
                  )}

                  <div className="card-footer">
                    <div className="stat-badge">
                      <span className="stat-val">{pipeline.nodes.length}</span>
                      <span className="stat-label">Nodes</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
      )}

      {runPipelineId && projectId && (
        <RunPipelineModal
          projectId={projectId}
          pipelineName={runPipelineId}
          onClose={() => setRunPipelineId(null)}
        />
      )}
    </div>
  );
}
