import { useMutation, useQueryClient } from "@tanstack/react-query";
import client from "../client";
import { toastStore } from "../../hooks/useModalStack";
import { defaultOnError } from "./errors";
import { qk } from "../queryKeys";

// ── Mutation payload types ────────────────────────────────────────────────────

interface SourceSelectPayload {
  path_or_url: string;
}

interface SetGitConfigPayload {
  name: string;
  email: string;
}

interface SaveConfigPayload {
  env: string;
  name: string;
  content: Record<string, unknown>;
  expected_commit_sha?: string;
}

// ── Source Mutations ──────────────────────────────────────────────────────────

/**
 * POST /workspace/select
 * Validates and selects a source directory or URL.
 */
export const useSelectSource = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: SourceSelectPayload) =>
      client.post("/workspace/select", data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.source() });
    },
    onError: defaultOnError,
  });
};

/**
 * PUT /git/config
 * Writes user.name and user.email to the workspace-local git config.
 */
export const useSetGitConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, email }: SetGitConfigPayload) =>
      client.put("/git/config", { name, email }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
    },
    onError: defaultOnError,
  });
};

/**
 * PUT /configs/{env}/{name}
 * Saves updated content for a single config file.
 */
export const useSaveConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ env, name, content, expected_commit_sha }: SaveConfigPayload) =>
      client.put(`/configs/${env}/${name}`, { content, expected_commit_sha }).then((r) => r.data),
    onSuccess: (data: { commit_sha?: string }) => {
      queryClient.invalidateQueries({ queryKey: qk.configs.all() });
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
      const sha = data?.commit_sha ? ` · ${data.commit_sha.slice(0, 7)}` : "";
      toastStore.getState().show(`Config saved${sha}`, "success");
    },
    onError: defaultOnError,
  });
};

/**
 * POST /configs/validate?env=
 * Validates the workspace configs for an environment against the ducta schemas.
 * Returns { valid, env, errors, warnings }.
 */
export const useValidateConfig = () =>
  useMutation({
    mutationFn: (env: string = "base") =>
      client.post("/configs/validate", null, { params: { env } }).then((r) => r.data),
    onError: defaultOnError,
  });

// ── Workspace File Mutations ──────────────────────────────────────────────────

/**
 * PUT /workspace/files/content
 * Creates or overwrites a text file in the workspace.
 */
export const useWriteWorkspaceFile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ path, content }: { path: string; content: string }) =>
      client.put("/workspace/files/content", { path, content }),
    onSuccess: (_data, { path }) => {
      const dir = path.includes("/") ? path.split("/").slice(0, -1).join("/") : "";
      queryClient.invalidateQueries({ queryKey: qk.files.all() });
      queryClient.invalidateQueries({ queryKey: qk.files.content(path) });
      queryClient.invalidateQueries({ queryKey: qk.files.dir(dir) });
    },
    onError: defaultOnError,
  });
};

/**
 * DELETE /workspace/files?path=
 * Deletes a file from the workspace.
 */
export const useDeleteWorkspaceFile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (path: string) =>
      client.delete("/workspace/files", { params: { path } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.files.all() });
    },
    onError: defaultOnError,
  });
};
