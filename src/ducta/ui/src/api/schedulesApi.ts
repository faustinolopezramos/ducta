import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "./client";
import { sourceKey } from "./utils";
import { toastStore } from "../hooks/useModalStack";

export interface PipelineSchedule {
  id: string;
  pipeline_name: string;
  project_id?: string | null;
  env: string;
  cron: string;
  enabled: boolean;
  hyperparams?: Record<string, unknown> | null;
  node_name?: string | null;
  created_at: string;
  last_run_at?: string | null;
  next_run_hint?: string | null;
}

export interface CreateScheduleVars {
  pipeline_name: string;
  cron: string;
  env?: string;
  project_id?: string;
  node_name?: string;
  hyperparams?: Record<string, unknown>;
}

export interface SchedulesListResult {
  schedules: PipelineSchedule[];
  count: number;
}

export const useSchedules = () =>
  useQuery<SchedulesListResult>({
    queryKey: ["schedules", sourceKey()],
    queryFn: () => client.get("/schedules").then((r) => r.data),
    staleTime: 10 * 1000,
  });

export const useCreateSchedule = () => {
  const qc = useQueryClient();
  return useMutation<PipelineSchedule, unknown, CreateScheduleVars>({
    mutationFn: (vars) => client.post("/schedules", vars).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schedules", sourceKey()] });
      toastStore.getState().show("Schedule created successfully", "success");
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toastStore.getState().show(detail ?? "Failed to create schedule", "error");
    },
  });
};

export const useDeleteSchedule = () => {
  const qc = useQueryClient();
  return useMutation<void, unknown, string>({
    mutationFn: (id) => client.delete(`/schedules/${id}`).then(() => undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schedules", sourceKey()] });
      toastStore.getState().show("Schedule removed", "info");
    },
  });
};

export const useToggleSchedule = () => {
  const qc = useQueryClient();
  return useMutation<PipelineSchedule, unknown, { id: string; enabled?: boolean }>({
    mutationFn: ({ id, enabled }) =>
      client.post(`/schedules/${id}/toggle`, null, { params: enabled !== undefined ? { enabled } : {} }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schedules", sourceKey()] });
    },
  });
};
