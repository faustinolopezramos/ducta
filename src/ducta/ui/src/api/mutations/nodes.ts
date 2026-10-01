import { useMutation, useQueryClient } from "@tanstack/react-query";
import client from "../client";
import { toastStore } from "../../hooks/useModalStack";
import { defaultOnError } from "./errors";
import { qk } from "../queryKeys";

/** Node identity is workspace-global, not project-scoped (PUT /nodes/{name}
 *  has no project_id) — but a node's spec feeds a project's own node-schema
 *  panel (`["server-projects", sourceKey(), projectId, "pipelines", ...,
 *  "nodes", ..., "schema"]`) and its dataset graph
 *  (`[..., projectId, "datasets"]`), neither of which shares the `["nodes"]`
 *  prefix these mutations invalidated on their own. Invalidating the whole
 *  `server-projects` tree too is the same generous, "just refetch everything
 *  that could plausibly be stale" pattern `useCreatePipeline`/
 *  `useDeletePipeline` already use (mutations/pipelines.ts). */
function invalidateNodeConsumers(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: qk.nodes.all() });
  queryClient.invalidateQueries({ queryKey: qk.projects.all() });
}

interface UpdateNodePayload {
  name: string;
  spec: Record<string, unknown>;
  expected_commit_sha?: string;
  /** Pipeline to create the node in. Required to create a node in a format-2
   *  project (ducta.yaml), where every node lives in a pipeline; format 1
   *  ignores it. */
  pipeline?: string;
}

interface UpdateNodeCodePayload {
  name: string;
  code: string;
}

// ── Node Mutations ────────────────────────────────────────────────────────────

/**
 * PUT /nodes/{name}
 * Creates or updates a node spec.
 */
export const useUpdateNode = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, spec, expected_commit_sha, pipeline }: UpdateNodePayload) =>
      client
        .put(`/nodes/${name}`, { spec, expected_commit_sha }, pipeline ? { params: { pipeline } } : undefined)
        .then((r) => r.data),
    onSuccess: () => invalidateNodeConsumers(queryClient),
    onError: defaultOnError,
  });
};

/**
 * PUT /nodes/{name}/code
 * Saves Python source code for a node.
 */
export const useUpdateNodeCode = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, code }: UpdateNodeCodePayload) =>
      client.put(`/nodes/${name}/code`, { code }).then((r) => r.data),
    onSuccess: (data: { commit_sha?: string }) => {
      invalidateNodeConsumers(queryClient);
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
      const sha = data?.commit_sha ? ` · ${data.commit_sha.slice(0, 7)}` : "";
      toastStore.getState().show(`Code saved${sha}`, "success");
    },
    onError: defaultOnError,
  });
};

/**
 * DELETE /nodes/{name}
 * Removes a node from the workspace config and commits to git.
 */
export const useDeleteNode = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => client.delete(`/nodes/${name}`).then(() => {}),
    onSuccess: () => invalidateNodeConsumers(queryClient),
    onError: defaultOnError,
  });
};
