import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import client from "./client";
import { defaultOnError } from "./mutations/errors";
import { qk } from "./queryKeys";

/**
 * The AI pipeline builder (`/api/ai/*`, `/api/projects/{id}/ai/*`).
 *
 * Drafting takes from seconds (a remote model) to minutes (a local one), so it
 * runs as a job: start it, then poll until it is done — each validation attempt
 * shows up as it ends. A draft is only written when it is applied.
 */

export interface AIProviderInfo {
  name: string;
  label: string;
  local: boolean;
  needs_key: boolean;
  default_base_url: string | null;
  default_model: string | null;
  api_key_env: string | null;
}

export interface AIKeyInfo {
  present: boolean;
  /** `env:NAME`, `keychain` or `none`. */
  source: string;
  masked: string;
}

export interface AISettings {
  configured: boolean;
  provider: string | null;
  label: string | null;
  model: string | null;
  endpoint: string | null;
  base_url: string | null;
  api_key_env: string | null;
  effort: string | null;
  max_attempts: number | null;
  timeout_seconds: number | null;
  is_local: boolean;
  key: AIKeyInfo;
  keychain_available: boolean;
  error: string | null;
  providers: AIProviderInfo[];
}

export interface AISettingsUpdate {
  provider: string;
  model?: string | null;
  base_url?: string | null;
  api_key_env?: string | null;
  effort?: string | null;
  max_attempts?: number | null;
}

export interface AIAttempt {
  number: number;
  files: string[];
  /** Errors the draft is responsible for. */
  errors: number;
  warnings: number;
  rejected: string[];
  usage: Record<string, number>;
  /** The first few problems sent back to the model (absent on older drafts). */
  messages?: string[];
}

export interface AIJob {
  id: string;
  project_id: string;
  kind: "new" | "fix" | "revise" | "quality" | "docs" | "explain" | "review";
  status: "running" | "done" | "failed" | "cancelled";
  started_at: string;
  finished_at: string | null;
  model: string | null;
  is_local: boolean;
  attempts: AIAttempt[];
  max_attempts: number;
  draft_id: string | null;
  ok: boolean | null;
  error: string | null;
  /** explain: the explanation, once done. */
  explanation?: string | null;
  /** review: the findings, once done. */
  review?: AIReview | null;
  execution_id?: string | null;
}

export interface AIExplanation {
  execution_id: string;
  text: string;
  model: string;
  created_at: string;
}

export interface AIReviewFinding {
  severity: "high" | "medium" | "low";
  area: "code" | "config" | "performance" | "quality" | "security";
  title: string;
  detail: string;
  suggestion: string;
  file: string | null;
  line: number | null;
  /** The line's text, as it is in the file. */
  code: string | null;
  /** The setting it is about. */
  key: string | null;
  /** `ducta`: certain; `ai`: the model's, checked against the code. */
  source: "ducta" | "ai";
}

export interface AIReview {
  pipeline: string;
  node: string;
  env: string;
  created_at: string;
  findings: AIReviewFinding[];
  /** null when only Ducta's checks ran. */
  model: string | null;
  /** The model's findings dropped: they pointed at nothing real. */
  dropped: number;
  notes: string;
}

export interface AIDocsGaps {
  datasets: number;
  pipelines: number;
  nodes: number;
}

export type AIJobRequest =
  | { kind: "new"; request: string }
  | { kind: "fix"; pipeline: string; note?: string; execution_id?: string }
  | { kind: "revise"; draft_id: string; note: string }
  | { kind: "quality"; pipeline: string; node: string; env?: string; note?: string }
  | { kind: "docs"; env?: string; note?: string }
  | { kind: "explain"; execution_id: string; note?: string }
  | { kind: "review"; pipeline: string; node: string; env?: string; note?: string };

export interface AIProblem {
  severity: "error" | "warning" | "info";
  message: string;
  code?: string;
  file?: string | null;
  line?: number | null;
  node?: string | null;
  pipeline?: string | null;
}

export interface AIDraftSummary {
  id: string;
  /** quality: a node's checks; docs: missing descriptions. */
  kind: "new" | "fix" | "quality" | "docs";
  request: string;
  pipeline: string | null;
  /** quality: the node. */
  target?: string | null;
  /** quality, docs: the environment whose data was read. */
  env?: string | null;
  provider: string;
  model: string;
  created_at: string;
  ok: boolean;
  files: string[];
  applied_at: string | null;
  revision_of: string | null;
}

export interface AIDraft extends AIDraftSummary {
  notes: string;
  /** What Ducta checked the draft against ("Proven on 2,431 rows of dev"). */
  evidence?: string;
  new_datasets: string[];
  file_contents: { path: string; content: string; change: "added" | "modified" }[];
  diff: string;
  problems: AIProblem[];
  blocking: AIProblem[];
  attempts: AIAttempt[];
  raw_answer: string;
  /** Files changed since the draft was made: applying it would be refused. */
  stale_files: string[];
}

// ── settings (the server's model) ─────────────────────────────────────────────

export const useAISettings = (enabled = true) =>
  useQuery<AISettings>({
    queryKey: qk.ai.settings(),
    queryFn: () => client.get("/ai/settings").then((r) => r.data),
    enabled,
    staleTime: 30 * 1000,
  });

export const useUpdateAISettings = () => {
  const qc = useQueryClient();
  return useMutation<AISettings, unknown, AISettingsUpdate>({
    mutationFn: (body) => client.put("/ai/settings", body).then((r) => r.data),
    onSuccess: (data) => {
      qc.setQueryData(qk.ai.settings(), data);
      qc.removeQueries({ queryKey: qk.ai.models() });
    },
    onError: defaultOnError,
  });
};

export const useStoreAIKey = () => {
  const qc = useQueryClient();
  return useMutation<AISettings, unknown, { api_key: string; provider?: string }>({
    mutationFn: (body) => client.put("/ai/key", body).then((r) => r.data),
    onSuccess: (data) => qc.setQueryData(qk.ai.settings(), data),
    onError: defaultOnError,
  });
};

export const useDeleteAIKey = () => {
  const qc = useQueryClient();
  return useMutation<AISettings, unknown, { provider?: string }>({
    mutationFn: ({ provider }) =>
      client.delete("/ai/key", { params: provider ? { provider } : undefined }).then((r) => r.data),
    onSuccess: (data) => qc.setQueryData(qk.ai.settings(), data),
    onError: defaultOnError,
  });
};

/** Test settings before saving them (needs `ai.configure`): the models that provider serves. */
export const useTestAIConnection = () =>
  useMutation<{ models: string[] }, unknown, AISettingsUpdate>({
    mutationFn: (body) => client.post("/ai/models/test", body, { timeout: 60_000 }).then((r) => r.data),
  });

/** The provider's models — fetched on demand, since it is also a connection test. */
export const useAIModels = () =>
  useQuery<{ models: string[] }>({
    queryKey: qk.ai.models(),
    queryFn: () => client.get("/ai/models", { timeout: 60_000 }).then((r) => r.data),
    enabled: false,
    retry: false,
  });

// ── jobs and drafts (per project) ─────────────────────────────────────────────

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/ai`;

export const useStartAIJob = (projectId: string) =>
  useMutation<AIJob, unknown, AIJobRequest>({
    mutationFn: (body) => client.post(`${base(projectId)}/jobs`, body).then((r) => r.data),
  });

/** A job, polled every 1.5 s while it runs. */
export const useAIJob = (projectId: string, jobId: string | null) => {
  const qc = useQueryClient();
  return useQuery<AIJob>({
    queryKey: qk.ai.job(projectId, jobId ?? ""),
    queryFn: async () => {
      const job: AIJob = (await client.get(`${base(projectId)}/jobs/${jobId}`)).data;
      if (job.status !== "running") qc.invalidateQueries({ queryKey: qk.ai.drafts(projectId) });
      if (job.status === "done" && job.kind === "explain" && job.execution_id) {
        qc.invalidateQueries({ queryKey: qk.ai.explanation(projectId, job.execution_id) });
      }
      if (job.status === "done" && job.kind === "review" && job.review) {
        qc.setQueryData(qk.ai.review(projectId, job.review.pipeline, job.review.node), job.review);
      }
      return job;
    },
    enabled: Boolean(jobId),
    refetchInterval: (query) => (query.state.data?.status === "running" || !query.state.data ? 1500 : false),
  });
};

/** Stop a running job: it reads as cancelled at once, and no draft is saved. */
export const useCancelAIJob = (projectId: string) => {
  const qc = useQueryClient();
  return useMutation<AIJob, unknown, string>({
    mutationFn: (jobId) => client.delete(`${base(projectId)}/jobs/${jobId}`).then((r) => r.data),
    onSuccess: (job) => qc.setQueryData(qk.ai.job(projectId, job.id), job),
    onError: defaultOnError,
  });
};

/**
 * Keep following a job after its dialog closes ("Run in background") and say
 * when it ends, since nothing on screen shows it any more.
 */
export function watchAIJobInBackground(
  projectId: string,
  jobId: string,
  notify: (message: string, tone: "success" | "error" | "info") => void,
  onEnd?: () => void,
): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const poll = async () => {
    if (stopped) return;
    let job: AIJob | null = null;
    try {
      job = (await client.get(`${base(projectId)}/jobs/${jobId}`)).data;
    } catch {
      job = null; // a blip: try again
    }
    if (stopped) return;
    if (job && job.status !== "running") {
      onEnd?.();
      if (job.status === "done") {
        notify(
          job.ok ? "The AI draft is ready to review." : "The AI draft is ready, with problems left to review.",
          job.ok ? "success" : "info",
        );
      } else if (job.status === "failed") {
        notify(job.error ?? "The AI draft failed.", "error");
      }
      return;
    }
    timer = setTimeout(poll, 3000);
  };
  timer = setTimeout(poll, 1500);
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}

/** A failed run's kept explanation; `null` when none was asked for yet. */
export const useAIExplanation = (projectId: string, executionId: string, enabled = true) =>
  useQuery<AIExplanation | null>({
    queryKey: qk.ai.explanation(projectId, executionId),
    queryFn: () =>
      client
        .get(`${base(projectId)}/explanations/${encodeURIComponent(executionId)}`, { expectedStatuses: [404] })
        .then((r) => r.data)
        .catch((e) => {
          if (e?.response?.status === 404) return null;
          throw e;
        }),
    enabled: enabled && Boolean(executionId),
    retry: false,
  });

const reviewPath = (projectId: string, pipeline: string, node: string) =>
  `${base(projectId)}/reviews/${encodeURIComponent(pipeline)}/${encodeURIComponent(node)}`;

/** A node's last review; `null` when it was never reviewed. */
export const useAIReview = (projectId: string, pipeline: string, node: string, enabled = true) =>
  useQuery<AIReview | null>({
    queryKey: qk.ai.review(projectId, pipeline, node),
    queryFn: () =>
      client
        .get(reviewPath(projectId, pipeline, node), { expectedStatuses: [404] })
        .then((r) => r.data)
        .catch((e) => {
          if (e?.response?.status === 404) return null;
          throw e;
        }),
    enabled: enabled && Boolean(projectId && pipeline && node),
    retry: false,
  });

/** Ducta's own checks of a node: at once, no model. Kept as its last review. */
export const useRunNodeChecks = (projectId: string, pipeline: string, node: string) => {
  const qc = useQueryClient();
  return useMutation<AIReview, unknown, { env: string }>({
    mutationFn: ({ env }) =>
      client.post(`${reviewPath(projectId, pipeline, node)}/checks`, null, { params: { env } }).then((r) => r.data),
    onSuccess: (review) => qc.setQueryData(qk.ai.review(projectId, pipeline, node), review),
  });
};

/** How many datasets, pipelines and nodes have no description. */
export const useAIDocsGaps = (projectId: string, enabled = true) =>
  useQuery<AIDocsGaps>({
    queryKey: qk.ai.docsGaps(projectId),
    queryFn: () => client.get(`${base(projectId)}/docs-gaps`).then((r) => r.data),
    enabled: enabled && Boolean(projectId),
    staleTime: 60 * 1000,
  });

export const useAIDrafts = (projectId: string, enabled = true) =>
  useQuery<AIDraftSummary[]>({
    queryKey: qk.ai.drafts(projectId),
    queryFn: () => client.get(`${base(projectId)}/drafts`).then((r) => r.data),
    enabled: enabled && Boolean(projectId),
  });

export const useAIDraft = (projectId: string, draftId: string | null) =>
  useQuery<AIDraft>({
    queryKey: qk.ai.draft(projectId, draftId ?? ""),
    queryFn: () => client.get(`${base(projectId)}/drafts/${draftId}`).then((r) => r.data),
    enabled: Boolean(draftId),
  });

export const useApplyAIDraft = (projectId: string) => {
  const qc = useQueryClient();
  return useMutation<{ draft_id: string; files: string[] }, unknown, { draftId: string; force?: boolean }>({
    mutationFn: ({ draftId, force }) =>
      client.post(`${base(projectId)}/drafts/${draftId}/apply`, { force: Boolean(force) }).then((r) => r.data),
    onSuccess: () => {
      // New pipelines, nodes, datasets and code: everything the project shows.
      qc.invalidateQueries({ queryKey: qk.projects.all() });
      qc.invalidateQueries({ queryKey: qk.nodes.all() });
      qc.invalidateQueries({ queryKey: qk.files.all() });
      qc.invalidateQueries({ queryKey: qk.git.all() });
      qc.invalidateQueries({ queryKey: qk.ai.project(projectId) });
    },
  });
};

export const useDeleteAIDraft = (projectId: string) => {
  const qc = useQueryClient();
  return useMutation<void, unknown, string>({
    mutationFn: (draftId) => client.delete(`${base(projectId)}/drafts/${draftId}`).then(() => undefined),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.ai.drafts(projectId) }),
    onError: defaultOnError,
  });
};
