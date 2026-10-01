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
