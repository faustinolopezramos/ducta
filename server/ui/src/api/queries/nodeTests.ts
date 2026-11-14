import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import client from "../client";

export interface TestResult {
  name: string;
  file?: string | null;
  line?: number | null;
  outcome: "passed" | "failed" | "error" | "skipped";
  message?: string | null;
  detail?: string | null;
  seconds: number;
}

export interface TestRun {
  ok: boolean;
  exit_code?: number | null;
  tests: TestResult[];
  summary: Record<string, number>;
  output: string;
}

const key = (projectId: string, node: string) => ["server-projects", projectId, "node-tests", node];

/** GET /projects/{id}/nodes/{node}/tests — the test files that cover the node. */
export const useNodeTests = (projectId: string, node: string) =>
  useQuery<{ files: string[] }>({
    queryKey: key(projectId, node),
    // 404: the node runs no project function — no tests to list.
    queryFn: () =>
      client
        .get(`/projects/${projectId}/nodes/${encodeURIComponent(node)}/tests`, { expectedStatuses: [404] })
        .then((r) => r.data),
    enabled: !!projectId && !!node,
    retry: false,
  });

/** POST /projects/{id}/tests/run — pytest, per-test outcome and the line it failed on. */
export const useRunNodeTests = (projectId: string) =>
  useMutation({
    mutationFn: (node: string) =>
      client.post(`/projects/${projectId}/tests/run`, { node }, { timeout: 15 * 60 * 1000 }).then((r) => r.data as TestRun),
  });

/** POST /projects/{id}/nodes/{node}/tests/snapshot — freeze inputs, pin the output's columns. */
export const useGenerateSnapshotTest = (projectId: string, node: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (v: { env: string; overwrite?: boolean }) =>
      client
        .post(`/projects/${projectId}/nodes/${encodeURIComponent(node)}/tests/snapshot`, { env: v.env, overwrite: !!v.overwrite })
        .then((r) => r.data as { test_file: string; fixtures: string[]; columns: string[]; rows: number }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: key(projectId, node) });
      queryClient.invalidateQueries({ queryKey: ["git"] });
    },
  });
};
