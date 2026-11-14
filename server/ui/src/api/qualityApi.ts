import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "./client";
import { defaultOnError } from "./mutations/errors";
import { qk } from "./queryKeys";

// ─── Types ────────────────────────────────────────────────────────────────────

/** One parameter of a check, as a JSON-Schema fragment (ducta.check.params). */
export interface QualityCheckParam {
  type?: string | string[];
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  description?: string;
}

export interface QualityCheckInfo {
  name: string;
  class_name: string;
  module: string;
  origin: string;
  /** First line of the check's docstring. */
  description?: string | null;
  /** What a failure counts as unless the check entry sets `severity`. */
  default_severity?: "ERROR" | "WARNING" | null;
  /** null when the check declares no parameters (some custom checks). */
  params?: Record<string, QualityCheckParam> | null;
}

export interface QualityDatasetRef {
  pipeline_name: string;
  dataset: string;
}

export interface QualityDatasetSummary {
  pipeline_name: string;
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
  env?: string;
}

export interface ValidateConfigResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

interface QualityScope {
  env?: string;
  pipelineName?: string;
  project?: string;
}

/** Wire params shared by every /quality/* request — mirrors mlopsApi.ts's
 *  `scopeParams`, which keeps `env`/`pipelineName`/`project` in one place
 *  instead of re-spelling `{ env, pipeline_name: pipelineName, project }` at
 *  every call site below. */
const scopeParams = ({ env, pipelineName, project }: QualityScope) => ({
  env,
  pipeline_name: pipelineName,
  project,
});

// ─── Query hooks ────────────────────────────────────────────────────────────────

export const useQualityChecks = () =>
  useQuery<QualityCheckInfo[]>({
    queryKey: qk.quality.checks(),
    queryFn: () => client.get("/quality/checks").then((r) => r.data),
    staleTime: 60 * 1000,
  });

export const useQualitySummary = (env?: string, pipelineName?: string, project?: string) =>
  useQuery<QualityDatasetSummary[]>({
    queryKey: qk.quality.summary({ env, pipelineName, project }),
    queryFn: () =>
      client
        .get("/quality/summary", { params: scopeParams({ env, pipelineName, project }) })
        .then((r) => r.data),
    staleTime: 15 * 1000,
  });

export const useQualityRuns = (
  dataset: string,
  env?: string,
  pipelineName?: string,
  project?: string,
  enabled = true
) =>
  useQuery<{ status: string; run_ids: string[] }>({
    queryKey: qk.quality.runs(dataset, { env, pipelineName, project }),
    queryFn: () =>
      client
        .get(`/quality/reports/${encodeURIComponent(dataset)}`, {
          params: { all: true, ...scopeParams({ env, pipelineName, project }) },
        })
        .then((r) => r.data),
    enabled: enabled && !!dataset,
    staleTime: 15 * 1000,
  });

export const useQualityReport = (
  dataset: string,
  runId?: string,
  env?: string,
  pipelineName?: string,
  project?: string,
  enabled = true
) =>
  useQuery({
    queryKey: qk.quality.report(dataset, runId, { env, pipelineName, project }),
    queryFn: () =>
      client
        .get(`/quality/reports/${encodeURIComponent(dataset)}`, {
          params: { run_id: runId, ...scopeParams({ env, pipelineName, project }) },
        })
        .then((r) => r.data),
    enabled: enabled && !!dataset,
    staleTime: 15 * 1000,
  });

/** Imperative one-off fetch (for the "Rerun" action, outside the query cache). */
export const fetchQualityReport = (
  dataset: string,
  runId: string,
  env?: string,
  pipelineName?: string,
  project?: string
) =>
  client
    .get(`/quality/reports/${encodeURIComponent(dataset)}`, {
      params: { run_id: runId, ...scopeParams({ env, pipelineName, project }) },
    })
    .then((r) => r.data);

export const useQualityScore = (
  runId: string,
  env?: string,
  pipelineName?: string,
  project?: string,
  enabled = true
) =>
  useQuery({
    queryKey: qk.quality.score(runId, { env, pipelineName, project }),
    queryFn: () =>
      client
        .get(`/quality/score/${encodeURIComponent(runId)}`, {
          params: scopeParams({ env, pipelineName, project }),
        })
        .then((r) => r.data),
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
      queryClient.invalidateQueries({ queryKey: qk.quality.all() });
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

interface DeleteQualityReportVars extends QualityScope {
  dataset: string;
  runId: string;
}

export const useDeleteQualityReport = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ dataset, runId, env, pipelineName, project }: DeleteQualityReportVars) =>
      client
        .delete(`/quality/reports/${encodeURIComponent(dataset)}/${encodeURIComponent(runId)}`, {
          params: scopeParams({ env, pipelineName, project }),
        })
        .then(() => undefined),
    onSuccess: (_data, { dataset }) => {
      queryClient.invalidateQueries({ queryKey: qk.quality.reports(dataset) });
    },
  });
};
