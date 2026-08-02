import { useMutation, useQueryClient } from "@tanstack/react-query";
import client from "../client";
import { toastStore } from "../../hooks/useModalStack";
import { defaultOnError } from "./errors";

interface UpdateNodePayload {
  name: string;
  spec: Record<string, unknown>;
  expected_commit_sha?: string;
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
    mutationFn: ({ name, spec, expected_commit_sha }: UpdateNodePayload) =>
      client.put(`/nodes/${name}`, { spec, expected_commit_sha }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["nodes"] });
    },
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
      queryClient.invalidateQueries({ queryKey: ["nodes"] });
      queryClient.invalidateQueries({ queryKey: ["git"] });
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["nodes"] });
    },
    onError: defaultOnError,
  });
};
