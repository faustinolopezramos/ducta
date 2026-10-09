import { useQuery } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

// ─────────────────────────────────────────────
// GIT QUERIES
// ─────────────────────────────────────────────

/**
 * GET /git/status
 * Returns { branch, commit, staged, unstaged, untracked }.
 */
export const useGitStatus = () =>
  useQuery({
    queryKey: qk.git.status(),
    queryFn: () => client.get("/git/status").then((r) => r.data),
    staleTime: 5 * 1000,
    refetchInterval: 30_000,
  });

/**
 * Whether the workspace is a Git repository — `undefined` until known. Diffs,
 * blame and history answer 409 without one, so callers ask this first.
 */
export const useGitAvailable = (): boolean | undefined => {
  const { data } = useGitStatus();
  return data ? Boolean((data as { available?: boolean }).available) : undefined;
};

/**
 * GET /git/log
 * Returns { commits: CommitInfo[], count }.
 * CommitInfo: { sha, short_sha, author, email, message, timestamp,
 *               files_changed, insertions, deletions }
 * Optional params: path (filter by file), limit (default 50, max 500).
 */
export const useGitLog = ({ path, limit = 50 }: { path?: string; limit?: number } = {}) =>
  useQuery({
    queryKey: qk.git.log(path, limit),
    queryFn: () =>
      client
        .get("/git/log", { params: { ...(path ? { path } : {}), limit } })
        .then((r) => r.data),
    staleTime: 30 * 1000,
  });

/**
 * GET /git/commit/{sha}
 * Returns CommitInfo for a single commit.
 */
export const useGitCommit = (sha: string) =>
  useQuery({
    queryKey: qk.git.commit(sha),
    queryFn: () => client.get(`/git/commit/${sha}`).then((r) => r.data),
    enabled: !!sha,
    staleTime: Infinity, // commits are immutable
  });

/**
 * GET /git/diff/{sha}
 * Returns DiffResponse { commit_a, commit_b, diff } — diff vs parent.
 */
export const useGitDiff = (sha: string) =>
  useQuery({
    queryKey: qk.git.diff(sha),
    queryFn: () => client.get(`/git/diff/${sha}`).then((r) => r.data),
    enabled: !!sha,
    staleTime: Infinity, // diffs are immutable
  });

export interface GitChange {
  path: string;
  status: "modified" | "added" | "deleted" | "untracked" | "renamed" | string;
  staged: boolean;
}

/**
 * GET /git/changes
 * Every uncommitted change — what the Changes panel lists before a commit.
 * Saving from the UI writes files; committing them is this explicit step.
 */
export const useGitChanges = (enabled = true) =>
  useQuery<{ available: boolean; branch: string; changes: GitChange[] }>({
    queryKey: qk.git.changes(),
    queryFn: () => client.get("/git/changes").then((r) => r.data),
    staleTime: 5 * 1000,
    refetchInterval: 30_000,
    enabled,
  });

/** GET /git/working-diff — a file at HEAD and on disk, for a side-by-side diff. */
export const useGitWorkingDiff = (path: string | null) =>
  useQuery<{ path: string; original: string; modified: string }>({
    queryKey: qk.git.workingDiff(path ?? ""),
    queryFn: () =>
      client.get("/git/working-diff", { params: { path }, expectedStatuses: [409] }).then((r) => r.data),
    enabled: !!path,
    staleTime: 0,
    retry: false, // a 409 (no Git) is the answer, not a hiccup
  });

/** GET /git/file-at — a file as it was at a commit. */
export const useGitFileAt = (path: string, rev: string | null | undefined) =>
  useQuery<{ path: string; rev: string; exists: boolean; content: string }>({
    queryKey: ["git", "file-at", path, rev],
    queryFn: () =>
      client.get("/git/file-at", { params: { path, rev }, expectedStatuses: [409] }).then((r) => r.data),
    enabled: !!path && !!rev,
    staleTime: Infinity, // a commit never changes
  });

export interface LastSuccess {
  pipeline: string;
  env: string;
  run_id?: string | null;
  started_at?: string | null;
  git_commit?: string | null;
  git_dirty?: boolean | null;
}

/** GET /projects/{id}/pipelines/{name}/last-success — the last good run, and the commit it ran. */
export const useLastSuccess = (projectId: string, pipeline: string | null, env: string) =>
  useQuery<LastSuccess>({
    queryKey: ["server-projects", projectId, "last-success", pipeline, env],
    queryFn: () => client.get(`/projects/${projectId}/pipelines/${pipeline}/last-success`, { params: { env } }).then((r) => r.data),
    enabled: !!projectId && !!pipeline,
    staleTime: 30 * 1000,
  });
