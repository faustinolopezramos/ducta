import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "./client";
import { sourceKey } from "./utils";
import { toastStore } from "../hooks/useModalStack";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface MetricPoint {
  key?: string;
  value: number;
  step?: number;
  timestamp?: string;
}

export interface ExperimentSummary {
  experiment_id: string;
  name?: string;
  created_at?: string;
  artifact_location?: string;
  tags?: Record<string, string>;
}

export interface ExperimentRun {
  run_id: string;
  experiment_id: string;
  name?: string;
  status: "RUNNING" | "COMPLETED" | "FAILED" | string;
  created_at?: string;
  start_time?: string | null;
  end_time?: string | null;
  duration_seconds?: number | null;
  parameters: Record<string, unknown>;
  /** metric key → time series; the last point is the final value. */
  metrics: Record<string, MetricPoint[]>;
  artifacts?: string[];
  tags: Record<string, string>;
  notes?: string;
}

export interface ExperimentDetail extends ExperimentSummary {
  runs: ExperimentRun[];
}

export interface ModelInfo {
  name: string;
  latest_version: number;
  stage?: string;
  framework?: string;
  created_at?: string;
}

export interface ModelVersion {
  version: number;
  created_at?: string;
  metadata?: {
    stage?: string;
    metrics?: Record<string, number>;
    [k: string]: unknown;
  };
}

/** Final (last-logged) value per metric key for a run. */
export const lastMetricValues = (run: ExperimentRun): Record<string, number> => {
  const out: Record<string, number> = {};
  for (const [key, series] of Object.entries(run.metrics ?? {})) {
    const last = series?.[series.length - 1];
    if (last && typeof last.value === "number") out[key] = last.value;
  }
  return out;
};

type ModelStage = "staging" | "production" | "archived";

interface PromoteModelVars {
  name: string;
  version: number;
  stage: ModelStage;
  force?: boolean;
}

interface GcVars {
  dry_run?: boolean;
}

interface GcResult {
  models_processed: number;
  versions_removed: number;
  bytes_freed: number;
  dry_run: boolean;
}

// ─── MLOps query hooks ────────────────────────────────────────────────────────

export const useMlopsExperiments = () =>
  useQuery<ExperimentSummary[]>({
    queryKey: ["mlops", sourceKey(), "experiments"],
    queryFn: () => client.get("/mlops/experiments").then((r) => r.data),
    staleTime: 30 * 1000,
  });

export const useMlopsExperiment = (experimentId: string) =>
  useQuery<ExperimentDetail>({
    queryKey: ["mlops", sourceKey(), "experiments", experimentId],
    queryFn: () =>
      client.get(`/mlops/experiments/${experimentId}`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!experimentId,
  });

export const useMlopsModels = () =>
  useQuery<ModelInfo[]>({
    queryKey: ["mlops", sourceKey(), "models"],
    queryFn: () => client.get("/mlops/models").then((r) => r.data),
    staleTime: 30 * 1000,
  });

export const useMlopsModelVersions = (name: string) =>
  useQuery<ModelVersion[]>({
    queryKey: ["mlops", sourceKey(), "models", name],
    queryFn: () => client.get(`/mlops/models/${name}`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!name,
  });

// ─── MLOps mutation hooks ─────────────────────────────────────────────────────

export const usePromoteModel = () => {
  const queryClient = useQueryClient();
  return useMutation<unknown, unknown, PromoteModelVars>({
    mutationFn: ({ name, version, stage, force = false }: PromoteModelVars) =>
      client
        .post(`/mlops/models/${name}/promote`, { version, stage, force })
        .then((r) => r.data),
    onSuccess: (_data, { name }) => {
      queryClient.invalidateQueries({ queryKey: ["mlops", sourceKey(), "models"] });
      queryClient.invalidateQueries({ queryKey: ["mlops", sourceKey(), "models", name] });
      toastStore.getState().show(`Model '${name}' promoted successfully`, "success");
    },
    onError: (error) => {
      const err = error as { response?: { data?: { message?: string } }; message?: string };
      const msg = err?.response?.data?.message ?? err?.message ?? "Promotion failed";
      toastStore.getState().error(`Operation failed: ${msg}`);
    },
  });
};

export const useCloseMlopsRun = () => {
  const queryClient = useQueryClient();
  return useMutation<
    { run_id: string; status: string },
    unknown,
    { experimentId: string; runId: string; status: "COMPLETED" | "FAILED" }
  >({
    mutationFn: ({ experimentId, runId, status }) =>
      client
        .post(`/mlops/experiments/${experimentId}/runs/${runId}/close`, { status })
        .then((r) => r.data),
    onSuccess: (_data, { experimentId }) => {
      queryClient.invalidateQueries({ queryKey: ["mlops", sourceKey(), "experiments", experimentId] });
    },
  });
};

export const useDeleteMlopsRun = () => {
  const queryClient = useQueryClient();
  return useMutation<void, unknown, { experimentId: string; runId: string }>({
    mutationFn: ({ experimentId, runId }) =>
      client.delete(`/mlops/experiments/${experimentId}/runs/${runId}`).then(() => undefined),
    onSuccess: (_data, { experimentId }) => {
      queryClient.invalidateQueries({ queryKey: ["mlops", sourceKey(), "experiments", experimentId] });
    },
  });
};

export const useDeleteModelVersion = () => {
  const queryClient = useQueryClient();
  return useMutation<void, unknown, { name: string; version: number }>({
    mutationFn: ({ name, version }) =>
      client.delete(`/mlops/models/${name}/versions/${version}`).then(() => undefined),
    onSuccess: (_data, { name }) => {
      queryClient.invalidateQueries({ queryKey: ["mlops", sourceKey(), "models"] });
      queryClient.invalidateQueries({ queryKey: ["mlops", sourceKey(), "models", name] });
    },
  });
};

export const useRunMlopsGc = () => {
  const queryClient = useQueryClient();
  return useMutation<GcResult, unknown, GcVars>({
    mutationFn: ({ dry_run = true }: GcVars) =>
      client.post("/mlops/gc", { dry_run }).then((r) => r.data),
    onSuccess: (data, { dry_run }) => {
      if (!dry_run) {
        queryClient.invalidateQueries({ queryKey: ["mlops", sourceKey(), "models"] });
      }
      const removed = data.versions_removed ?? 0;
      const msg = dry_run
        ? `GC dry run: ${removed} versions would be removed`
        : `GC complete: ${removed} versions removed`;
      toastStore.getState().show(msg, "success");
    },
    onError: (error) => {
      const err = error as { response?: { data?: { message?: string } }; message?: string };
      const msg = err?.response?.data?.message ?? err?.message ?? "GC failed";
      toastStore.getState().error(`Operation failed: ${msg}`);
    },
  });
};
