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
  /** The user's hyperparameters. */
  parameters: Record<string, unknown>;
  /** What Ducta records about the run for itself (environment snapshot, input
   *  fingerprints, code hash): the parameters whose name starts with `_`. */
  internal_parameters?: Record<string, unknown>;
  /** metric key → time series; the last point is the final value. */
  metrics: Record<string, MetricPoint[]>;
  artifacts?: string[];
  tags: Record<string, string>;
  notes?: string;
}

export interface ExperimentDetail extends ExperimentSummary {
  runs: ExperimentRun[];
}

/** A project node that scores with a model (`model:` on a serving node). */
export interface ModelServedBy {
  pipeline: string | null;
  node: string;
  /** What the node asks for: a stage, resolved when each run starts… */
  stage: string | null;
  /** …or an exact version. */
  version: number | null;
  streaming: boolean;
}

export interface ModelInfo {
  name: string;
  latest_version: number;
  stage?: string;
  framework?: string;
  created_at?: string;
  served_by?: ModelServedBy[];
}

/** Mirrors ModelRegistry.list_model_versions. */
export interface ModelVersion {
  version: number;
  stage?: string;
  created_at?: string;
  artifact_type?: string;
  framework?: string;
  metrics?: Record<string, number>;
  hyperparameters?: Record<string, unknown>;
  /** The registered input schema's columns: what the built-in scorer feeds the model. */
  features?: string[] | null;
  /** Recorded at registration; serving refuses a copy that no longer matches. */
  artifact_sha256?: string | null;
  size_bytes?: number | null;
  experiment_run_id?: string | null;
}

/** One row of the run table (GET /mlops/run-table): a run joined with the model it
 *  registered and its certificate. Beyond the fixed columns, `param_<name>` are its
 *  hyperparameters and `metric_<name>` its final metrics; a column no run has a
 *  value for is absent. */
export interface RunTableRow {
  run_id: string;
  pipeline: string;
  run_name?: string | null;
  status: string;
  started_at?: string | null;
  duration_seconds?: number | null;
  sweep_id?: string | null;
  model_name?: string | null;
  model_version?: number | null;
  model_stage?: string | null;
  model_label?: string | null;
  artifact_sha256?: string | null;
  git_commit?: string | null;
  code_hash?: string | null;
  data_hash?: string | null;
  split_applied?: boolean | null;
  /** The id of the run's certificate, as recorded when it ran. */
  certificate_id?: string | null;
  /** True: found and unaltered. False: missing or altered. Absent: not checked. */
  certificate_ok?: boolean | null;
  [column: string]: unknown;
}

export interface RunTable {
  /** Column keys, in display order. */
  columns: string[];
  rows: RunTableRow[];
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

/** A model persisted as plain files (MLOps was off for the run): servable, but
 *  with no experiment and no registry entry. */
export interface UnregisteredModel {
  name: string;
  versions: number;
  latest: string | null;
  updated_at: string;
}

/** Why the experiments / registry views are empty (GET /mlops/status). */
export interface MlopsStatus {
  storage_path: string;
  /** The setting runs of this environment use. */
  mlops_enabled: boolean;
  tracking_present: boolean;
  registry_present: boolean;
  unregistered_models: UnregisteredModel[];
}

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

export const useMlopsStatus = (env?: string, pipelineName?: string, project?: string) =>
  useQuery<MlopsStatus>({
    queryKey: qk.mlops.status({ env, pipelineName, project }),
    queryFn: () =>
      client
        .get("/mlops/status", { params: scopeParams({ env, pipelineName, project }) })
        .then((r) => r.data),
    enabled: !!pipelineName,
    staleTime: 30 * 1000,
  });

/** The run table with each run's certificate checked, newest first. */
export const useMlopsRunTable = (env?: string, pipelineName?: string, project?: string) =>
  useQuery<RunTable>({
    queryKey: qk.mlops.runTable({ env, pipelineName, project }),
    queryFn: () =>
      client
        .get("/mlops/run-table", {
          params: { ...scopeParams({ env, pipelineName, project }), verify_certificates: true },
        })
        .then((r) => r.data),
    enabled: !!pipelineName,
    staleTime: 30 * 1000,
  });

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
      queryClient.invalidateQueries({ queryKey: qk.mlops.runTable({ env, pipelineName, project }) });
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
      queryClient.invalidateQueries({ queryKey: qk.mlops.runTable({ env, pipelineName, project }) });
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
      queryClient.invalidateQueries({ queryKey: qk.mlops.runTable({ env, pipelineName, project }) });
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
