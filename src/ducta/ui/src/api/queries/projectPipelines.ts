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
