import { useQuery } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

// ─────────────────────────────────────────────
// PIPELINE QUERIES  (project-scoped — canonical)
// ─────────────────────────────────────────────

/**
 * GET /projects/{projectId}/pipelines
 * Returns { project_id, pipelines: { [name]: spec }, count, commit_sha }.
 * `commit_sha` is the whole project's pipelines.yaml version — pass it back
 * as `expectedSha` on useUpdatePipeline/useDeletePipeline for OCC.
 */
export const useServerProjectPipelines = (projectId: string) =>
  useQuery({
    queryKey: qk.projects.pipelines(projectId),
    queryFn: () =>
      client.get(`/projects/${projectId}/pipelines`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!projectId,
  });

export interface ProjectDependencyEdge {
  from_pipeline: string;
  from_node: string;
  to_pipeline: string;
  to_node: string;
  dataset?: string | null;
  kind: "explicit" | "dataset" | string;
}

export interface ProjectDependencies {
  project_id: string;
  pipelines: Record<string, string[]>;
  edges: ProjectDependencyEdge[];
}

/**
 * GET /projects/{projectId}/dependencies
 * Node/pipeline dependency graph (explicit deps + shared datasets).
 */
export const useProjectDependencies = (projectId: string) =>
  useQuery<ProjectDependencies>({
    queryKey: qk.projects.dependencies(projectId),
    queryFn: () =>
      client.get(`/projects/${projectId}/dependencies`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!projectId,
  });

/**
 * GET /projects/{projectId}/pipelines/{name}
 * Returns { name, spec, project_id }.
 */
export const useProjectPipeline = (projectId: string, name: string) =>
  useQuery({
    queryKey: qk.projects.pipeline(projectId, name),
    queryFn: () =>
      client.get(`/projects/${projectId}/pipelines/${name}`).then((r) => r.data),
    staleTime: 60 * 1000,
    enabled: !!projectId && !!name,
  });

/** What one node of an ML pipeline is given (`ducta config show --ml`). */
export interface MlPlanNode {
  ml_stage: string;
  split?: Record<string, unknown>;
  split_from?: "node" | "pipeline";
  /** Bound to apply the split: the run fails (or warns) if the node does not. */
  must_apply_split?: boolean;
  hyperparams?: Record<string, unknown>;
  model_version?: string;
  /** The registered model a serving node scores with, as declared (`model:`). */
  model?: MlPlanModel;
  /** "built-in scorer" when a serving node has no `run` of its own. */
  run?: string;
  /** Which registered version the model's stage names right now. */
  model_resolution?: MlPlanModelResolution;
}

export interface MlPlanModelResolution {
  /** resolved: found in the registry · unresolved: nothing to serve yet ·
   *  at_run_time: an MLflow model · unknown: the registry could not be read. */
  status: "resolved" | "unresolved" | "at_run_time" | "unknown";
  version?: number;
  stage?: string | null;
  framework?: string;
  artifact_sha256?: string | null;
  message?: string;
}

export interface MlPlanModel {
  source?: "ducta" | "mlflow";
  name?: string;
  stage?: string;
  version?: number;
  uri?: string;
  features?: string[];
  output_col?: string;
  method?: string;
}

export interface MlPlan {
  pipeline: string;
  env: string;
  type?: string | null;
  split_enforcement?: "error" | "warn" | null;
  split?: Record<string, unknown> | null;
  /** Empty for a pipeline without ML. */
  nodes: Record<string, MlPlanNode>;
}

/**
 * GET /projects/{projectId}/pipelines/{name}/ml-plan?env=
 * What each ML node will be given, resolved as the engine resolves it. Reads
 * configuration only.
 */
export const useMlPlan = (projectId: string, pipeline: string, env: string) =>
  useQuery<MlPlan>({
    queryKey: qk.projects.mlPlan(projectId, pipeline, env),
    queryFn: () =>
      client
        .get(`/projects/${projectId}/pipelines/${pipeline}/ml-plan`, { params: { env } })
        .then((r) => r.data),
    staleTime: 60 * 1000,
    enabled: !!projectId && !!pipeline,
  });
