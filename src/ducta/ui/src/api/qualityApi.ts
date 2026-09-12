import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "./client";
import { sourceKey } from "./utils";
import { defaultOnError } from "./mutations/errors";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface QualityCheckInfo {
  name: string;
  class_name: string;
  module: string;
  origin: string;
}

export interface QualityDatasetSummary {
  dataset: string;
  run_count: number;
  latest_run_id?: string | null;
  latest_score?: number | null;
  passed?: boolean | null;
  created_at?: string | null;
  trend: (number | null)[];
}

export interface RunChecksVars {
  input_path: string;
  format?: "parquet" | "csv" | "json";
  config_path?: string;
  checks?: Record<string, unknown>;
  fail_fast?: boolean;
}

export interface ValidateConfigVars {
  node_name: string;
  config_path: string;
  global_config_path?: string;
}

export interface ValidateConfigResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

// ─── Query hooks ────────────────────────────────────────────────────────────────

export const useQualityChecks = () =>
  useQuery<QualityCheckInfo[]>({
    queryKey: ["quality", sourceKey(), "checks"],
    queryFn: () => client.get("/quality/checks").then((r) => r.data),
    staleTime: 60 * 1000,
  });

export const useQualitySummary = () =>
  useQuery<QualityDatasetSummary[]>({
    queryKey: ["quality", sourceKey(), "summary"],
    queryFn: () => client.get("/quality/summary").then((r) => r.data),
    staleTime: 15 * 1000,
  });

export const useQualityDatasets = () =>
  useQuery<string[]>({
    queryKey: ["quality", sourceKey(), "datasets"],
    queryFn: () => client.get("/quality/datasets").then((r) => r.data),
    staleTime: 15 * 1000,
  });

export const useQualityRuns = (dataset: string, enabled = true) =>
  useQuery<{ status: string; run_ids: string[] }>({
    queryKey: ["quality", sourceKey(), "reports", dataset, "all"],
    queryFn: () =>
      client
        .get(`/quality/reports/${encodeURIComponent(dataset)}`, { params: { all: true } })
        .then((r) => r.data),
    enabled: enabled && !!dataset,
    staleTime: 15 * 1000,
  });

export const useQualityReport = (dataset: string, runId?: string, enabled = true) =>
  useQuery({
    queryKey: ["quality", sourceKey(), "reports", dataset, runId ?? "latest"],
    queryFn: () =>
      client
        .get(`/quality/reports/${encodeURIComponent(dataset)}`, {
          params: runId ? { run_id: runId } : {},
        })
        .then((r) => r.data),
    enabled: enabled && !!dataset,
    staleTime: 15 * 1000,
  });

export const useQualityTrend = (dataset: string, lastN = 20, enabled = true) =>
  useQuery({
    queryKey: ["quality", sourceKey(), "trend", dataset, lastN],
    queryFn: () =>
      client
        .get(`/quality/trend/${encodeURIComponent(dataset)}`, { params: { last_n: lastN } })
        .then((r) => r.data),
    enabled: enabled && !!dataset,
    staleTime: 15 * 1000,
  });

/** Imperative one-off fetch (for the "Rerun" action, outside the query cache). */
export const fetchQualityReport = (dataset: string, runId: string) =>
  client
    .get(`/quality/reports/${encodeURIComponent(dataset)}`, { params: { run_id: runId } })
    .then((r) => r.data);

export const useQualityScore = (runId: string, enabled = true) =>
  useQuery({
    queryKey: ["quality", sourceKey(), "score", runId],
    queryFn: () =>
      client.get(`/quality/score/${encodeURIComponent(runId)}`).then((r) => r.data),
    enabled: enabled && !!runId,
    staleTime: 15 * 1000,
  });

// ─── Mutation hooks ─────────────────────────────────────────────────────────────

export const useRunQualityChecks = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: RunChecksVars) =>
      client.post("/quality/run", vars).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quality", sourceKey()] });
    },
    onError: defaultOnError,
  });
};

export const useValidateQualityConfig = () =>
  useMutation({
    mutationFn: (vars: ValidateConfigVars) =>
      client.post<ValidateConfigResult>("/quality/validate-config", vars).then((r) => r.data),
    onError: defaultOnError,
  });

export const useDeleteQualityReport = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ dataset, runId }: { dataset: string; runId: string }) =>
      client
        .delete(`/quality/reports/${encodeURIComponent(dataset)}/${encodeURIComponent(runId)}`)
        .then(() => undefined),
    onSuccess: (_data, { dataset }) => {
      queryClient.invalidateQueries({ queryKey: ["quality", sourceKey(), "reports", dataset] });
    },
  });
};
