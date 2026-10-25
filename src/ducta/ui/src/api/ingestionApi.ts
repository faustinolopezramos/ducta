import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
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

/**
 * Connections live in each project's sources.yaml, so every call names the
 * project of the page it is made from. Without it, a workspace holding several
 * projects answered with none of their connections.
 */
function useProjectParams(): { project?: string } {
  const { projectId } = useParams<{ projectId?: string }>();
  return projectId ? { project: projectId } : {};
}

// ─── Hooks ──────────────────────────────────────────────────────────────────────

export const useConnections = () => {
  const params = useProjectParams();
  return useQuery<{ connections: ConnectionInfo[] }>({
    queryKey: qk.ingestion.connections(params.project),
    queryFn: () => client.get("/ingestion/connections", { params }).then((r) => r.data),
    staleTime: 30 * 1000,
  });
};

export const useTestConnection = () => {
  const params = useProjectParams();
  return useMutation<ConnectionTestResult, unknown, ConnectionTestVars>({
    mutationFn: (vars) => client.post("/ingestion/connections/test", vars, { params }).then((r) => r.data),
    onError: defaultOnError,
  });
};

export const useCreateConnection = () => {
  const qc = useQueryClient();
  const params = useProjectParams();
  return useMutation<ConnectionInfo, unknown, ConnectionCreateVars>({
    mutationFn: (vars) => client.post("/ingestion/connections", vars, { params }).then((r) => r.data),
    onSuccess: () => invalidate(qc),
    onError: defaultOnError,
  });
};

export const useDeleteConnection = () => {
  const qc = useQueryClient();
  const params = useProjectParams();
  return useMutation<void, unknown, string>({
    mutationFn: (name) =>
      client.delete(`/ingestion/connections/${encodeURIComponent(name)}`, { params }).then(() => undefined),
    onSuccess: () => invalidate(qc),
    onError: defaultOnError,
  });
};

export const useRetestConnection = () => {
  const params = useProjectParams();
  return useMutation<ConnectionTestResult, unknown, string>({
    mutationFn: (name) =>
      client.post(`/ingestion/connections/${encodeURIComponent(name)}/test`, undefined, { params }).then((r) => r.data),
  });
};

export const useConnectionUsage = (name: string, enabled: boolean) => {
  const params = useProjectParams();
  return useQuery<ConnectionUsageResult>({
    queryKey: qk.ingestion.usage(name, params.project),
    queryFn: () =>
      client.get(`/ingestion/connections/${encodeURIComponent(name)}/usage`, { params }).then((r) => r.data),
    enabled: enabled && !!name,
    staleTime: 15 * 1000,
  });
};

/** GET /ingestion/connections/{name}/credentials — whether each variable is set, never its value. */
export const useConnectionCredentials = (name: string | null | undefined) => {
  const params = useProjectParams();
  return useQuery<{ connection: string; variables: { name: string; set: boolean; where?: string | null }[] }>({
    queryKey: ["ingestion", "credentials", params.project ?? null, name],
    queryFn: () =>
      client.get(`/ingestion/connections/${encodeURIComponent(name!)}/credentials`, { params }).then((r) => r.data),
    enabled: !!name,
    retry: false,
  });
};
