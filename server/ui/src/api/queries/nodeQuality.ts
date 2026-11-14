import { useMutation, useQuery } from "@tanstack/react-query";
import client from "../client";

export interface NodeQualityBlock {
  checks?: Record<string, Record<string, unknown> | null>;
  gate?: Record<string, unknown>;
  [key: string]: unknown;
}

/** GET …/nodes/{node}/quality — the node's quality block as written, and what it writes. */
export const useNodeQuality = (projectId: string, pipeline: string, node: string) =>
  useQuery<{
    quality: NodeQualityBlock | null;
    outputs: string[];
    uses_template?: string | null;
    kind?: string;
    ingest?: Record<string, unknown> | null;
  }>({
    queryKey: ["server-projects", projectId, "node-quality", pipeline, node],
    queryFn: () =>
      client
        .get(`/projects/${projectId}/pipelines/${encodeURIComponent(pipeline)}/nodes/${encodeURIComponent(node)}/quality`)
        .then((r) => r.data),
    enabled: !!projectId && !!pipeline && !!node,
  });

export interface TriedCheck {
  check_name: string;
  /** null when the check could not be tried here (it needs Spark). */
  passed: boolean | null;
  not_tried?: boolean;
  severity?: string;
  message?: string;
}

/** POST /projects/{id}/quality/try — a draft of checks on the dataset's data, nothing saved. */
export const useTryChecks = (projectId: string) =>
  useMutation({
    mutationFn: (v: { dataset: string; env: string; checks: Record<string, unknown> }) =>
      client
        .post(`/projects/${projectId}/quality/try`, v, { timeout: 5 * 60 * 1000 })
        .then((r) => r.data as { passed: boolean; results: TriedCheck[]; sampled_rows: number; total_rows?: number | null }),
  });

export interface FailingRowsResult {
  check: string;
  failing: number;
  scanned: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

/** POST /projects/{id}/quality/failing-rows — the rows a check objects to. */
export const useFailingRows = (
  projectId: string,
  v: { dataset: string; env: string; check: string; params: Record<string, unknown> } | null,
) =>
  useQuery<FailingRowsResult>({
    queryKey: ["server-projects", projectId, "failing-rows", v],
    queryFn: () => client.post(`/projects/${projectId}/quality/failing-rows`, v).then((r) => r.data),
    enabled: !!projectId && !!v,
    retry: false,
  });
