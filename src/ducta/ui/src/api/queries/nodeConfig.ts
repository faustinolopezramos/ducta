import { useQuery } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

export interface EffectiveConfigRow {
  key: string;
  values: Record<string, unknown>;
  /** node | pipeline defaults | project defaults | framework default */
  sources: Record<string, string>;
  overridden: Record<string, boolean>;
}

/** GET …/nodes/{node}/effective-config — each setting per environment, and where it comes from. */
export const useEffectiveConfig = (projectId: string, pipeline: string, node: string) =>
  useQuery<{ environments: string[]; rows: EffectiveConfigRow[] }>({
    queryKey: [...qk.projects.pipeline(projectId, pipeline), "effective-config", node],
    queryFn: () =>
      client.get(`/projects/${projectId}/pipelines/${pipeline}/nodes/${node}/effective-config`).then((r) => r.data),
    enabled: !!projectId && !!pipeline && !!node,
    staleTime: 10 * 1000,
  });

export interface DatasetPreview {
  dataset: string;
  env: string;
  available: boolean;
  reason?: string | null;
  path?: string | null;
  format?: string | null;
  columns: { name: string; type: string }[];
  rows: Record<string, unknown>[];
  total_rows?: number | null;
}

/** GET /projects/{id}/datasets/{name}/preview — first rows and columns, as materialized in `env`. */
export const useDatasetPreview = (projectId: string, dataset: string | null, env: string, limit = 50, scratch = false) =>
  useQuery<DatasetPreview>({
    queryKey: [...qk.projects.detail(projectId), "preview", dataset, env, limit, scratch],
    queryFn: () =>
      client
        .get(`/projects/${projectId}/datasets/${dataset}/preview`, { params: { env, limit, scratch } })
        .then((r) => r.data),
    enabled: !!projectId && !!dataset,
    staleTime: 30 * 1000,
  });

export interface NodeTemplate {
  name: string;
  file: string;
  description?: string | null;
  params?: { name: string; required: boolean; default?: unknown }[];
  run?: string | null;
  /** Set when the template file does not read. */
  error?: string;
}

/** GET /projects/{id}/templates/nodes — `templates/nodes/*.yaml`. */
export const useNodeTemplates = (projectId: string) =>
  useQuery<{ templates: NodeTemplate[] }>({
    queryKey: ["server-projects", projectId, "node-templates"],
    queryFn: () => client.get(`/projects/${projectId}/templates/nodes`).then((r) => r.data),
    enabled: !!projectId,
    staleTime: 30 * 1000,
  });

/** GET /projects/{id}/templates/pipelines — subpipelines, used as `use: pipeline:<name>`. */
export const usePipelineTemplates = (projectId: string) =>
  useQuery<{ templates: (NodeTemplate & { nodes?: string[] })[] }>({
    queryKey: ["server-projects", projectId, "pipeline-templates"],
    queryFn: () => client.get(`/projects/${projectId}/templates/pipelines`).then((r) => r.data),
    enabled: !!projectId,
    staleTime: 30 * 1000,
  });
