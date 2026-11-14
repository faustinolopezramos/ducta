import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";
import { defaultOnError, extractError } from "../mutations/errors";

/** A problem the UI can act on: where it is, what it is about, how to fix it. */
export interface Problem {
  severity: "error" | "warning" | "info";
  message: string;
  /** Stable kind: unknown_dataset, unknown_key, cycle, function_not_found, … */
  code: string;
  /** Which check found it: config, code, graph, preflight. */
  source: string;
  /** Project-relative. */
  file?: string | null;
  line?: number | null;
  column?: number | null;
  node?: string | null;
  pipeline?: string | null;
  dataset?: string | null;
  /** Replace the first `replace[0]` in `file` with `replace[1]`. */
  fix?: { label: string; replace: [string, string] } | null;
}

export interface ValidateResult {
  ok: boolean;
  problems: Problem[];
}

/**
 * POST /projects/{id}/validate
 * The project as it would be with `files` (unsaved text) applied — config in
 * every environment, then each node's `run:` against its function. Nothing is
 * written, nothing imported: cheap enough to run while typing.
 */
export const useValidateProject = () =>
  useMutation({
    mutationFn: ({ projectId, files = {} }: { projectId: string; files?: Record<string, string> }) =>
      client.post<ValidateResult>(`/projects/${projectId}/validate`, { files }).then((r) => r.data),
  });

export interface PipelineSource {
  pipeline: string;
  file: string;
  workspace_file: string;
  content: string;
  version: string;
}

/** GET /projects/{id}/pipelines/{name}/source — the pipeline's file, comments included. */
export const usePipelineSource = (projectId: string, name: string) =>
  useQuery<PipelineSource>({
    queryKey: [...qk.projects.pipeline(projectId, name), "source"],
    queryFn: () => client.get(`/projects/${projectId}/pipelines/${name}/source`).then((r) => r.data),
    enabled: !!projectId && !!name,
    staleTime: 5 * 1000,
  });

/**
 * PUT /projects/{id}/pipelines/{name}/source — written as given, kept only if
 * the project still validates (400 with problems otherwise). Not committed.
 */
export const useSavePipelineSource = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, name, content, expectedVersion }: { projectId: string; name: string; content: string; expectedVersion?: string }) =>
      client
        .put<PipelineSource>(`/projects/${projectId}/pipelines/${name}/source`, { content, expected_version: expectedVersion })
        .then((r) => r.data),
    onSuccess: (_d, { projectId }) => {
      queryClient.invalidateQueries({ queryKey: qk.projects.detail(projectId) });
      queryClient.invalidateQueries({ queryKey: qk.projects.all() });
      queryClient.invalidateQueries({ queryKey: qk.nodes.all() });
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
    },
    onError: defaultOnError,
  });
};

/** Problems in a 400 from a write: `detail.items` when the server split them. */
export function problemsFromError(err: unknown): Problem[] {
  const detail = extractError(err).detail as { items?: Problem[] } | undefined;
  return Array.isArray(detail?.items) ? detail.items : [];
}
