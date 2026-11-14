import { useMutation, useQueryClient } from "@tanstack/react-query";
import client from "../client";
import { toastStore } from "../../hooks/useModalStack";
import { defaultOnError } from "./errors";
import { qk } from "../queryKeys";

interface GitRevertPayload {
  path: string;
  commit: string;
  message?: string;
}

// ── Git Mutations ─────────────────────────────────────────────────────────────

/**
 * POST /git/stage
 * Stages files for commit. Pass no paths to stage all changes.
 */
export const useGitStage = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ paths, force }: { paths?: string[]; force?: boolean } = {}) =>
      client.post("/git/stage", { ...(paths ? { paths } : {}), ...(force ? { force } : {}) }).then((r) => r.data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: qk.git.all() }); },
    onError: defaultOnError,
  });
};

/**
 * POST /git/commit
 * Commits — `paths` stages exactly those files first; without it, whatever is
 * already staged. The author goes on the commit only, never into git config.
 */
export const useGitCommitChanges = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      message,
      author_name,
      author_email,
      paths,
    }: { message?: string; author_name?: string; author_email?: string; paths?: string[] } = {}) =>
      client.post("/git/commit", { message, author_name, author_email, ...(paths ? { paths } : {}) }).then((r) => r.data),
    onSuccess: (data: { success?: boolean; commit_hash?: string | null; message?: string }) => {
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
      if (data?.success === false) {
        toastStore.getState().show(data.message ?? "Nothing to commit", "info");
        return;
      }
      const sha = data?.commit_hash ? ` · ${String(data.commit_hash).slice(0, 7)}` : "";
      toastStore.getState().show(`Changes committed${sha}`, "success");
    },
    onError: defaultOnError,
  });
};

/**
 * POST /git/revert
 * Restores a file to its state at a given commit.
 */
export const useGitRevert = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ path, commit, message }: GitRevertPayload) =>
      client.post("/git/revert", { path, commit, ...(message ? { message } : {}) }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
    },
    onError: defaultOnError,
  });
};

/**
 * Push local commits to the remote.
 *
 * Repointed from the removed `/repository/push`: that route went through the
 * multi-cloud adapter stack (GitHub/Azure/CodeCommit), while `/git/push` drives
 * the same local repository through GitSyncManager and takes no branch — it
 * pushes the checked-out one.
 */
export const useGitPush = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      client.post("/git/push").then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
    },
    onError: defaultOnError,
  });
};

export const useGitPull = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      client.post("/git/pull").then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
    },
    onError: defaultOnError,
  });
};
