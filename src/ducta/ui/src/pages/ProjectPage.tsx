import { useParams, useNavigate, Link } from "react-router-dom";
import { useMemo, useState, useRef, useEffect } from "react";
import { useProjectStore } from "../store/projectStore";
import { selectPresent } from "../store/reducer";
import { useServerPipelineHydration } from "../hooks/useServerPipelineHydration";
import { useCreatePipeline, useDeletePipeline } from "../api/mutations";
import { useProjectDependencies, useServerProjectPipelines } from "../api/queries";
import { computeLineage, lensEdgeClass } from "../utils/lineage";
import { useBuilderStore } from "../store/builderStore";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { DagCanvas } from "../components/Pipeline/DagCanvas";
import {
  IconChevronRight,
  IconPlus,
  IconTrash,
  IconLayoutGrid,
  IconSitemap,
  IconArrowRight,
} from "@tabler/icons-react";

const MAX_PREVIEW_NODES = 6;

/** Project map: pipelines as supernodes, edges labelled with the shared
 *  datasets. Click selects (dependency lens), double-click previews the
 *  pipeline's nodes in place, "Open" navigates to the full workspace. */
function ProjectDependenciesView({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const { data, isLoading, isError } = useProjectDependencies(projectId);
  const { data: pipelinesData } = useServerProjectPipelines(projectId);
  const [selectedPipeline, setSelectedPipeline] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  // The DAG canvas shares the builder-store viewport; start the map at 1:1
  // instead of inheriting the zoom/pan of the last pipeline workspace.
  const resetViewport = useBuilderStore((s) => s.resetViewport);
  useEffect(() => { resetViewport(); }, [resetViewport]);

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

  const lineage = useMemo(
    () => computeLineage(selectedPipeline, parents),
    [selectedPipeline, parents]
  );

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  if (isLoading) {
    return (
      <div style={{ padding: 24 }}>
        <Skeleton variant="block" height="200px" />
      </div>
    );
  }
  if (isError) {
    return (
      <EmptyState
        icon={IconSitemap}
        title="Couldn't load the project map"
        description="Check that the API is reachable and try again."
      />
    );
  }
  if (items.length === 0) {
    return <EmptyState icon={IconSitemap} title="No pipelines in this project yet" />;
  }

  const hasCrossEdges = labels.size > 0 || items.some((i) => i.dependsOn.length > 0);

  return (
    <div style={{ position: "relative" }}>
      {!hasCrossEdges && (
        <p style={{ margin: "12px 0 0", fontSize: 12, color: "var(--text-muted)" }}>
          No cross-pipeline dependencies detected — pipelines neither declare dependencies on each
          other's nodes nor consume each other's output datasets.
        </p>
      )}
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
          const lensDepth = lensDir === "up" ? lineage!.upstream.get(item.id) : lineage!?.downstream.get(item.id);
          const dimmed = lineage ? item.id !== lineage.selectedId && !lensDir : false;
          const isSelected = selectedPipeline === item.id;
          const isExpanded = expanded.has(item.id);
          const previewNodes = (item.nodes as string[]).slice(0, MAX_PREVIEW_NODES);
          return (
            <div
              role="button"
              tabIndex={0}
              aria-pressed={isSelected}
              aria-label={`Pipeline ${item.id}, ${item.nodeCount} nodes`}
              className={`pipeline-supernode ${isSelected ? "selected" : ""} ${dimmed ? "dag-dimmed" : ""} ${lensDir ? `lens-${lensDir}` : ""}`}
              onClick={() => setSelectedPipeline((cur) => (cur === item.id ? null : item.id))}
              onDoubleClick={() => {
                setSelectedPipeline(item.id);
                toggleExpanded(item.id);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  navigate(`/project/${projectId}/pipeline/${item.id}`);
                }
                if (e.key === " ") {
                  e.preventDefault();
                  setSelectedPipeline((cur) => (cur === item.id ? null : item.id));
                }
              }}
            >
              {lensDir && lensDepth != null && (
                <span className={`lens-tag lens-tag-${lensDir}`}>
                  {lensDir === "up" ? "↑" : "↓"}{lensDepth}
                </span>
              )}
              <div className="supernode-head">
                <span className="supernode-name">{item.id}</span>
                <span className="supernode-type">{pipelineType}</span>
              </div>
              <div className="supernode-meta">
                <span>{item.nodeCount} node{item.nodeCount !== 1 ? "s" : ""}</span>
                <button
                  className="supernode-open"
                  onClick={(e) => {
                    e.stopPropagation();
                    navigate(`/project/${projectId}/pipeline/${item.id}`);
                  }}
                  aria-label={`Open pipeline ${item.id}`}
                >
                  Open <IconArrowRight size={11} />
                </button>
              </div>
              {isExpanded && (
                <div className="supernode-inner">
                  {previewNodes.map((n) => (
                    <span key={n} className="supernode-mini-node">{n}</span>
                  ))}
                  {item.nodes.length > MAX_PREVIEW_NODES && (
                    <span className="supernode-more">+{item.nodes.length - MAX_PREVIEW_NODES} more</span>
                  )}
                </div>
              )}
            </div>
          );
        }}
      />
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
              edges: [],
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
      { projectId, name: pipelineId },
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

  return (
    <div className="page-transition project-page">
      {/* Header with breadcrumb */}
      <div className="project-header">
        <div className="breadcrumbs">
          <Link to="/projects" className="breadcrumb-item">Projects</Link>
          <IconChevronRight size={14} className="separator" />
          <span className="breadcrumb-current">{currentProject.name}</span>
        </div>

        <div className="header-actions">
          <Button variant="primary" size="sm" onClick={handleOpenCreate}>
            <IconPlus size={16} stroke={2} />
            <span>New Pipeline</span>
          </Button>
        </div>
      </div>

      <div className="project-content t-container">
        {/* Project Intro */}
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
          <div className="section-header" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h2 className="t-h2">{view === "pipelines" ? "Pipelines" : "Project map"}</h2>
            <div style={{ display: "flex", gap: 6 }}>
              <Button
                variant={view === "dependencies" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setView("dependencies")}
                title="Cross-pipeline dependency map (explicit deps + shared datasets)"
              >
                <IconSitemap size={14} />
                Map
              </Button>
              <Button
                variant={view === "pipelines" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setView("pipelines")}
              >
                <IconLayoutGrid size={14} />
                List
              </Button>
            </div>
          </div>

          {view === "dependencies" && projectId ? (
            <ProjectDependenciesView projectId={projectId} />
          ) : (
            <>
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
                  onClick={() => navigate(`/project/${projectId}/pipeline/${pipeline.id}`)}
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
                    <div className="delete-confirm-overlay" onClick={e => e.stopPropagation()}>
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
            </>
          )}
        </section>
      </div>
    </div>
  );
}
