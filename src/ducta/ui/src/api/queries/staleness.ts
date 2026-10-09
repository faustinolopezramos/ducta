import { useQuery } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

/** Whether a node still matches its pipeline's last successful run in an environment. */
export interface NodeFreshness {
  node: string;
  pipeline?: string | null;
  state: "fresh" | "stale" | "never";
  reasons: string[];
  last_run_id?: string | null;
  last_run_at?: string | null;
}

/**
 * GET /projects/{id}/staleness?env= — per node: fresh, stale (its function or
 * something upstream changed since the last good run) or never run.
 */
export const useStaleness = (projectId: string, env: string) =>
  useQuery<NodeFreshness[]>({
    queryKey: [...qk.projects.detail(projectId), "staleness", env],
    queryFn: () => client.get(`/projects/${projectId}/staleness`, { params: { env } }).then((r) => r.data),
    enabled: !!projectId,
    staleTime: 15 * 1000,
  });
