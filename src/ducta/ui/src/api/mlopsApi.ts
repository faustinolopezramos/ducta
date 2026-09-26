import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "./client";
import { toastStore } from "../hooks/useModalStack";
import { defaultOnError } from "./mutations/errors";
import { qk } from "./queryKeys";

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

interface MlopsScope {
  env?: string;
  pipelineName?: string;
  project?: string;
}

interface PromoteModelVars extends MlopsScope {
  name: string;
  version: number;
  stage: ModelStage;
  force?: boolean;
}

interface GcVars extends MlopsScope {
  dry_run?: boolean;
}

interface GcResult {
  models_processed: number;
  versions_removed: number;
  bytes_freed: number;
  dry_run: boolean;
}

/** Wire params shared by every /mlops/* request — `pipeline`/`project` are the
 *  route's actual query-param names (routes/mlops.py), distinct from this
 *  file's `pipelineName` to keep call sites readable. */
const scopeParams = ({ env, pipelineName, project }: MlopsScope) => ({
  env,
  pipeline: pipelineName,
  project,
});

// ─── MLOps query hooks ────────────────────────────────────────────────────────

export const useMlopsExperiments = (env?: string, pipelineName?: string, project?: string) =>
  useQuery<ExperimentSummary[]>({
    queryKey: qk.mlops.experiments({ env, pipelineName, project }),
    queryFn: () =>
      client
        .get("/mlops/experiments", { params: scopeParams({ env, pipelineName, project }) })
        .then((r) => r.data),
    enabled: !!pipelineName,
    staleTime: 30 * 1000,
  });

export const useMlopsExperiment = (
  experimentId: string,
  env?: string,
  pipelineName?: string,
  project?: string
) =>
  useQuery<ExperimentDetail>({
    queryKey: qk.mlops.experiment(experimentId, { env, pipelineName, project }),
    queryFn: () =>
      client
        .get(`/mlops/experiments/${experimentId}`, {
          params: scopeParams({ env, pipelineName, project }),
        })
        .then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!experimentId && !!pipelineName,
  });

export const useMlopsModels = (env?: string, pipelineName?: string, project?: string) =>
  useQuery<ModelInfo[]>({
    queryKey: qk.mlops.models({ env, pipelineName, project }),
    queryFn: () =>
      client
        .get("/mlops/models", { params: scopeParams({ env, pipelineName, project }) })
        .then((r) => r.data),
    enabled: !!pipelineName,
    staleTime: 30 * 1000,
  });

export const useMlopsModelVersions = (
  name: string,
  env?: string,
  pipelineName?: string,
  project?: string
) =>
  useQuery<ModelVersion[]>({
    queryKey: qk.mlops.modelVersions(name, { env, pipelineName, project }),
    queryFn: () =>
      client
        .get(`/mlops/models/${name}`, { params: scopeParams({ env, pipelineName, project }) })
        .then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!name && !!pipelineName,
  });

// ─── MLOps mutation hooks ─────────────────────────────────────────────────────

export const usePromoteModel = () => {
  const queryClient = useQueryClient();
  return useMutation<unknown, unknown, PromoteModelVars>({
    mutationFn: ({ name, version, stage, force = false, env, pipelineName, project }) =>
      client
        .post(
          `/mlops/models/${name}/promote`,
          { version, stage, force },
          { params: scopeParams({ env, pipelineName, project }) }
        )
        .then((r) => r.data),
    onSuccess: (_data, { name, env, pipelineName, project }) => {
      queryClient.invalidateQueries({
        queryKey: qk.mlops.models({ env, pipelineName, project }),
      });
      queryClient.invalidateQueries({
        queryKey: qk.mlops.modelVersions(name, { env, pipelineName, project }),
      });
      toastStore.getState().show(`Model '${name}' promoted successfully`, "success");
    },
    onError: defaultOnError,
  });
};

export const useCloseMlopsRun = () => {
  const queryClient = useQueryClient();
  return useMutation<
    { run_id: string; status: string },
    unknown,
    MlopsScope & { experimentId: string; runId: string; status: "COMPLETED" | "FAILED" }
  >({
    mutationFn: ({ experimentId, runId, status, env, pipelineName, project }) =>
      client
        .post(
          `/mlops/experiments/${experimentId}/runs/${runId}/close`,
          { status },
          { params: scopeParams({ env, pipelineName, project }) }
        )
        .then((r) => r.data),
    onSuccess: (_data, { experimentId, env, pipelineName, project }) => {
      queryClient.invalidateQueries({
        queryKey: qk.mlops.experiment(experimentId, { env, pipelineName, project }),
      });
    },
    onError: defaultOnError,
  });
};

export const useDeleteMlopsRun = () => {
  const queryClient = useQueryClient();
  return useMutation<void, unknown, MlopsScope & { experimentId: string; runId: string }>({
    mutationFn: ({ experimentId, runId, env, pipelineName, project }) =>
      client
        .delete(`/mlops/experiments/${experimentId}/runs/${runId}`, {
          params: scopeParams({ env, pipelineName, project }),
        })
        .then(() => undefined),
    onSuccess: (_data, { experimentId, env, pipelineName, project }) => {
      queryClient.invalidateQueries({
        queryKey: qk.mlops.experiment(experimentId, { env, pipelineName, project }),
      });
    },
    onError: defaultOnError,
  });
};

export const useDeleteModelVersion = () => {
  const queryClient = useQueryClient();
  return useMutation<void, unknown, MlopsScope & { name: string; version: number }>({
    mutationFn: ({ name, version, env, pipelineName, project }) =>
      client
        .delete(`/mlops/models/${name}/versions/${version}`, {
          params: scopeParams({ env, pipelineName, project }),
        })
        .then(() => undefined),
    onSuccess: (_data, { name, env, pipelineName, project }) => {
      queryClient.invalidateQueries({
        queryKey: qk.mlops.models({ env, pipelineName, project }),
      });
      queryClient.invalidateQueries({
        queryKey: qk.mlops.modelVersions(name, { env, pipelineName, project }),
      });
    },
    onError: defaultOnError,
  });
};

export const useRunMlopsGc = () => {
  const queryClient = useQueryClient();
  return useMutation<GcResult, unknown, GcVars>({
    mutationFn: ({ dry_run = true, env, pipelineName, project }) =>
      client
        .post("/mlops/gc", { dry_run }, { params: scopeParams({ env, pipelineName, project }) })
        .then((r) => r.data),
    onSuccess: (data, { dry_run, env, pipelineName, project }) => {
      if (!dry_run) {
        queryClient.invalidateQueries({
          queryKey: qk.mlops.models({ env, pipelineName, project }),
        });
      }
      const removed = data.versions_removed ?? 0;
      const msg = dry_run
        ? `GC dry run: ${removed} versions would be removed`
        : `GC complete: ${removed} versions removed`;
      toastStore.getState().show(msg, "success");
    },
    onError: defaultOnError,
  });
};
