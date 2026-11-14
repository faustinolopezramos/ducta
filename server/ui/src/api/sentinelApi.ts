import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import client from "./client";
import type { AIJob } from "./aiApi";
import { defaultOnError } from "./mutations/errors";
import { qk } from "./queryKeys";

/**
 * Ducta Sentinel API (`/api/projects/{id}/sentinel/*`).
 *
 * Its status, the project's incidents, and what a person does with them:
 * resolve, ignore, re-run, pause and resume (`sentinel.manage`), and ask the
 * model for a proposal (an AI job, `ai.use`). Levels are the engine's: L0
 * observes (a person acts), L1 acts on its own (a re-run), L2 proposes.
 */

export interface SentinelStatus {
  enabled: boolean;
  paused: boolean;
  environments: string[];
  protected: string[];
  pipelines: string[];
  actions_today: number;
  max_actions_per_day: number;
  active: number;
  escalated: number;
  error: string | null;
}

export type IncidentStatus =
  | "open"
  | "remediating"
  | "escalated"
  | "resolved"
  | "ignored";

export type IncidentLevel = "L0" | "L1" | "L2";

export interface IncidentTimelineEntry {
  at: string;
  actor: string;
  action: string;
  detail?: string;
}

export interface IncidentModel {
  id: string;
  env: string;
  pipeline: string;
  kind: string;
  status: IncidentStatus;
  opened_at: string;
  updated_at: string;
  resolved_at?: string;
  diagnosis: Record<string, any>;
  runbook: string;
  level: IncidentLevel;
  reason: string;
  failures: number;
  attempts: number;
  last_run_id?: string;
  pending?: Record<string, any> | null;
  links: {
    draft?: string;
    explanation?: string;
    [key: string]: any;
  };
  timeline: IncidentTimelineEntry[];
}

export interface IncidentFilter {
  status?: string;
  env?: string;
}

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/sentinel`;

export const useSentinelStatus = (projectId: string, enabled = true) =>
  useQuery<SentinelStatus>({
    queryKey: qk.sentinel.status(projectId),
    queryFn: () => client.get(`${base(projectId)}/status`).then((r) => r.data),
    enabled: enabled && Boolean(projectId),
    refetchInterval: 10_000,
  });

export const useSentinelIncidents = (
  projectId: string,
  filters?: IncidentFilter,
  enabled = true,
) =>
  useQuery<IncidentModel[]>({
    queryKey: qk.sentinel.incidents(projectId, filters),
    queryFn: () =>
      client
        .get(`${base(projectId)}/incidents`, { params: filters })
        .then((r) => r.data),
    enabled: enabled && Boolean(projectId),
    refetchInterval: 5_000,
  });

export const useSentinelIncident = (
  projectId: string,
  incidentId: string | null,
  enabled = true,
) =>
  useQuery<IncidentModel>({
    queryKey: qk.sentinel.incident(projectId, incidentId ?? ""),
    queryFn: () =>
      client
        .get(`${base(projectId)}/incidents/${encodeURIComponent(incidentId ?? "")}`)
        .then((r) => r.data),
    enabled: enabled && Boolean(projectId && incidentId),
    refetchInterval: 3_000,
  });

export const usePauseSentinel = (projectId: string) => {
  const qc = useQueryClient();
  return useMutation<SentinelStatus, unknown, { note?: string }>({
    mutationFn: (body) =>
      client.post(`${base(projectId)}/pause`, body).then((r) => r.data),
    onSuccess: (status) => {
      qc.setQueryData(qk.sentinel.status(projectId), status);
    },
    onError: defaultOnError,
  });
};

export const useResumeSentinel = (projectId: string) => {
  const qc = useQueryClient();
  return useMutation<SentinelStatus, unknown, { note?: string }>({
    mutationFn: (body) =>
      client.post(`${base(projectId)}/resume`, body).then((r) => r.data),
    onSuccess: (status) => {
      qc.setQueryData(qk.sentinel.status(projectId), status);
    },
    onError: defaultOnError,
  });
};

export const useResolveIncident = (projectId: string) => {
  const qc = useQueryClient();
  return useMutation<IncidentModel, unknown, { incidentId: string; note?: string }>({
    mutationFn: ({ incidentId, note }) =>
      client
        .post(`${base(projectId)}/incidents/${encodeURIComponent(incidentId)}/resolve`, {
          note,
        })
        .then((r) => r.data),
    onSuccess: (incident) => {
      qc.setQueryData(qk.sentinel.incident(projectId, incident.id), incident);
      qc.invalidateQueries({ queryKey: qk.sentinel.incidents(projectId) });
      qc.invalidateQueries({ queryKey: qk.sentinel.status(projectId) });
    },
    onError: defaultOnError,
  });
};

export const useIgnoreIncident = (projectId: string) => {
  const qc = useQueryClient();
  return useMutation<IncidentModel, unknown, { incidentId: string; note?: string }>({
    mutationFn: ({ incidentId, note }) =>
      client
        .post(`${base(projectId)}/incidents/${encodeURIComponent(incidentId)}/ignore`, {
          note,
        })
        .then((r) => r.data),
    onSuccess: (incident) => {
      qc.setQueryData(qk.sentinel.incident(projectId, incident.id), incident);
      qc.invalidateQueries({ queryKey: qk.sentinel.incidents(projectId) });
      qc.invalidateQueries({ queryKey: qk.sentinel.status(projectId) });
    },
    onError: defaultOnError,
  });
};

export const useRetryIncident = (projectId: string) => {
  const qc = useQueryClient();
  return useMutation<IncidentModel, unknown, { incidentId: string }>({
    mutationFn: ({ incidentId }) =>
      client
        .post(`${base(projectId)}/incidents/${encodeURIComponent(incidentId)}/retry`, {})
        .then((r) => r.data),
    onSuccess: (incident) => {
      qc.setQueryData(qk.sentinel.incident(projectId, incident.id), incident);
      qc.invalidateQueries({ queryKey: qk.sentinel.incidents(projectId) });
      qc.invalidateQueries({ queryKey: qk.sentinel.status(projectId) });
    },
    onError: defaultOnError,
  });
};

/**
 * Ask the model to explain an incident and draft a fix. It is an AI job
 * (`kind: sentinel_propose`, needs `ai.use`): started, then followed until it
 * ends, since the model takes minutes. Resolves with the finished job; the
 * explanation and draft are linked to the incident.
 */
export const useProposeFix = (projectId: string) => {
  const qc = useQueryClient();
  const jobs = `/projects/${encodeURIComponent(projectId)}/ai/jobs`;
  return useMutation<AIJob, unknown, { incidentId: string }>({
    mutationFn: async ({ incidentId }) => {
      let job: AIJob = (
        await client.post(jobs, { kind: "sentinel_propose", incident_id: incidentId })
      ).data;
      while (job.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        job = (await client.get(`${jobs}/${job.id}`)).data;
      }
      if (job.status !== "done") throw new Error(job.error ?? "The proposal did not finish.");
      return job;
    },
    onSettled: (_job, _err, { incidentId }) => {
      qc.invalidateQueries({ queryKey: qk.sentinel.incident(projectId, incidentId) });
      qc.invalidateQueries({ queryKey: qk.sentinel.incidents(projectId) });
      qc.invalidateQueries({ queryKey: qk.ai.drafts(projectId) });
    },
  });
};
