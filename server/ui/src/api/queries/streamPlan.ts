import { useQuery } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

export interface StreamPlanIssue {
  level: "error" | "warning";
  text: string;
}

/** One stream node as `ducta stream plan` resolves it: what it would do, nothing started. */
export interface StreamPlanNode {
  name: string;
  source: string;
  sink: string;
  trigger: string;
  output_mode: string;
  checkpoint?: string | null;
  after: string[];
  transform?: string | null;
  quarantine?: string | null;
  quality?: string | null;
  issues: StreamPlanIssue[];
}

export interface StreamPlan {
  pipeline: string;
  env?: string | null;
  /** False when something would stop the stream from starting. */
  ok: boolean;
  nodes: StreamPlanNode[];
  /** Problems not tied to one node. */
  issues: StreamPlanIssue[];
}

/** POST …/stream-plan once, for a caller that is not a hook (a Start button that checks first). */
export const fetchStreamPlan = (projectId: string, pipeline: string, env: string): Promise<StreamPlan> =>
  client
    .post(`/projects/${projectId}/pipelines/${pipeline}/stream-plan`, null, { params: { env } })
    .then((r) => r.data);

/**
 * POST …/stream-plan — what a streaming pipeline would do in `env`, without starting it.
 * A POST because it imports the project's transforms (in a subprocess); it changes nothing.
 */
export const useStreamPlan = (projectId: string, pipeline: string, env: string, enabled = true) =>
  useQuery<StreamPlan>({
    queryKey: [...qk.projects.pipeline(projectId, pipeline), "stream-plan", env],
    queryFn: () => fetchStreamPlan(projectId, pipeline, env),
    enabled: enabled && !!projectId && !!pipeline,
    staleTime: 10 * 1000,
    retry: false,
  });
