import { useMutation, useQueryClient } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

/** One canvas edit; see api/repositories/pipeline_ops.py for the full list. */
export type PipelineOp =
  | { op: "connect"; node: string; dataset: string; alias?: string | null }
  | { op: "disconnect"; node: string; dataset: string }
  | { op: "add_output" | "remove_output"; node: string; dataset: string }
  | { op: "add_node"; node: string; use?: string; with?: Record<string, unknown>; run?: string; kind?: string; description?: string; inputs?: Record<string, string> | string[]; outputs?: string[]; body?: Record<string, unknown> }
  | { op: "remove_node"; node: string }
  | { op: "set"; node: string; key: string; value: unknown };

export interface PipelineOpsResult {
  version: string;
  /** Applying these undoes the edit. */
  inverse: PipelineOp[];
}

/**
 * POST /projects/{id}/pipelines/{name}/ops — edit the pipeline's file in
 * place (comments kept), validated with the whole project, not committed.
 */
export const usePipelineOps = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      pipeline,
      ops,
      expectedVersion,
      newDatasets,
    }: {
      projectId: string;
      pipeline: string;
      ops: PipelineOp[];
      expectedVersion?: string;
      newDatasets?: Record<string, Record<string, unknown>>;
    }) =>
      client
        .post<PipelineOpsResult>(`/projects/${projectId}/pipelines/${pipeline}/ops`, {
          ops,
          expected_version: expectedVersion,
          new_datasets: newDatasets ?? {},
        })
        .then((r) => r.data),
    onSuccess: (_d, { projectId }) => {
      queryClient.invalidateQueries({ queryKey: qk.projects.detail(projectId) });
      queryClient.invalidateQueries({ queryKey: qk.projects.all() });
      queryClient.invalidateQueries({ queryKey: qk.nodes.all() });
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
    },
  });
};

/** Move a node's configuration into `templates/nodes/<template>.yaml`; the node then `use`s it. */
export const useExtractNodeTemplate = (projectId: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (v: { pipeline: string; node: string; template: string; params: string[] }) =>
      client
        .post(`/projects/${projectId}/pipelines/${encodeURIComponent(v.pipeline)}/nodes/${encodeURIComponent(v.node)}/extract-template`, {
          template: v.template,
          params: v.params,
        })
        .then((r) => r.data as { template: string; file: string }),
    onSuccess: () => {
      // Two files changed: every view of the project's configuration is stale.
      queryClient.invalidateQueries({ queryKey: ["server-projects", projectId] });
      queryClient.invalidateQueries({ queryKey: ["git"] });
    },
  });
};

/** Move nodes into `templates/pipelines/<template>.yaml`; one `use: pipeline:` node takes their place. */
export const useExtractSubpipeline = (projectId: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (v: { pipeline: string; nodes: string[]; template: string }) =>
      client
        .post(`/projects/${projectId}/pipelines/${encodeURIComponent(v.pipeline)}/extract-subpipeline`, {
          template: v.template,
          nodes: v.nodes,
        })
        .then((r) => r.data as { template: string; file: string }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["server-projects", projectId] });
      queryClient.invalidateQueries({ queryKey: ["git"] });
    },
  });
};
