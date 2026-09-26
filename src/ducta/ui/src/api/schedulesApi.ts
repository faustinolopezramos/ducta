import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "./client";
import { toastStore } from "../hooks/useModalStack";
import { defaultOnError } from "./mutations/errors";
import { qk } from "./queryKeys";

export interface PipelineSchedule {
  id: string;
  pipeline_name: string;
  project_id?: string | null;
  user_id?: string | null;
  env: string;
  cron: string;
  enabled: boolean;
  hyperparams?: Record<string, unknown> | null;
  node_name?: string | null;
  created_at: string;
  last_run_at?: string | null;
  last_execution_id?: string | null;
  next_run_at?: string | null;
}

export interface CreateScheduleVars {
  pipeline_name: string;
  cron: string;
  env?: string;
  project_id?: string;
  node_name?: string;
  hyperparams?: Record<string, unknown>;
}

export interface UpdateScheduleVars {
  id: string;
  pipeline_name?: string;
  cron?: string;
  env?: string;
  node_name?: string;
  hyperparams?: Record<string, unknown>;
}

export interface SchedulesListResult {
  schedules: PipelineSchedule[];
  count: number;
}

export const useSchedules = () =>
  useQuery<SchedulesListResult>({
    queryKey: qk.schedules(),
    queryFn: () => client.get("/schedules").then((r) => r.data),
    staleTime: 10 * 1000,
  });

export const useCreateSchedule = () => {
  const qc = useQueryClient();
  return useMutation<PipelineSchedule, unknown, CreateScheduleVars>({
    mutationFn: (vars) => client.post("/schedules", vars).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.schedules() });
      toastStore.getState().show("Schedule created successfully", "success");
    },
    onError: defaultOnError,
  });
};

export const useUpdateSchedule = () => {
  const qc = useQueryClient();
  return useMutation<PipelineSchedule, unknown, UpdateScheduleVars>({
    mutationFn: ({ id, ...body }) => client.patch(`/schedules/${id}`, body).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.schedules() });
      toastStore.getState().show("Schedule updated", "success");
    },
    onError: defaultOnError,
  });
};

export const useDeleteSchedule = () => {
  const qc = useQueryClient();
  return useMutation<void, unknown, string>({
    mutationFn: (id) => client.delete(`/schedules/${id}`).then(() => undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.schedules() });
      toastStore.getState().show("Schedule removed", "info");
    },
    onError: defaultOnError,
  });
};

export const useToggleSchedule = () => {
  const qc = useQueryClient();
  return useMutation<PipelineSchedule, unknown, { id: string; enabled?: boolean }>({
    mutationFn: ({ id, enabled }) =>
      client.post(`/schedules/${id}/toggle`, null, { params: enabled !== undefined ? { enabled } : {} }).then((r) => r.data),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: qk.schedules() });
      toastStore.getState().show(updated.enabled ? "Schedule activated" : "Schedule paused", "success");
    },
    onError: defaultOnError,
  });
};
