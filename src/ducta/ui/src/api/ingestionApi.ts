import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "./client";
import { defaultOnError } from "./mutations/errors";
import { qk } from "./queryKeys";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ConnectionInfo {
  name: string;
  type?: string;
  host?: string;
  port?: number;
  database?: string;
  description?: string;
}

export interface ConnectionCreateVars {
  name: string;
  type: string;
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  description?: string;
  overwrite?: boolean;
}

export type ConnectionTestVars = Omit<ConnectionCreateVars, "name" | "description" | "overwrite">;

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
}

export interface ConnectionUsageItem {
  execution_id: string;
  pipeline_name: string;
  project_id?: string;
  status: string;
  started_at?: string;
}

export interface ConnectionUsageResult {
  pipelines: string[];
  executions: ConnectionUsageItem[];
}

const invalidate = (qc: ReturnType<typeof useQueryClient>) =>
  qc.invalidateQueries({ queryKey: qk.ingestion.all() });

// ─── Hooks ──────────────────────────────────────────────────────────────────────

export const useConnections = () =>
  useQuery<{ connections: ConnectionInfo[] }>({
    queryKey: qk.ingestion.connections(),
    queryFn: () => client.get("/ingestion/connections").then((r) => r.data),
    staleTime: 30 * 1000,
  });

export const useTestConnection = () =>
  useMutation<ConnectionTestResult, unknown, ConnectionTestVars>({
    mutationFn: (vars) => client.post("/ingestion/connections/test", vars).then((r) => r.data),
    onError: defaultOnError,
  });

export const useCreateConnection = () => {
  const qc = useQueryClient();
  return useMutation<ConnectionInfo, unknown, ConnectionCreateVars>({
    mutationFn: (vars) => client.post("/ingestion/connections", vars).then((r) => r.data),
    onSuccess: () => invalidate(qc),
    onError: defaultOnError,
  });
};

export const useDeleteConnection = () => {
  const qc = useQueryClient();
  return useMutation<void, unknown, string>({
    mutationFn: (name) => client.delete(`/ingestion/connections/${encodeURIComponent(name)}`).then(() => undefined),
    onSuccess: () => invalidate(qc),
    onError: defaultOnError,
  });
};

export const useRetestConnection = () =>
  useMutation<ConnectionTestResult, unknown, string>({
    mutationFn: (name) =>
      client.post(`/ingestion/connections/${encodeURIComponent(name)}/test`).then((r) => r.data),
  });

export const useConnectionUsage = (name: string, enabled: boolean) =>
  useQuery<ConnectionUsageResult>({
    queryKey: qk.ingestion.usage(name),
    queryFn: () =>
      client.get(`/ingestion/connections/${encodeURIComponent(name)}/usage`).then((r) => r.data),
    enabled: enabled && !!name,
    staleTime: 15 * 1000,
  });
