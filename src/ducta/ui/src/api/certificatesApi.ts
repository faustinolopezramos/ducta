/**
 * Run Certificates + deep preflight — API hooks.
 *
 * Every terminating run emits a tamper-evident Run Certificate; these hooks let
 * the UI list/inspect/verify them and run the same deep preflight as
 * `ducta config validate` before executing a pipeline.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { executionClient } from "./client";

// ── Types (mirror ducta.api.routes.certificates / projects.PreflightResponse) ──

export interface CertificateVerifyResult {
  ok: boolean;
  run_id?: string | null;
  reason: string;
  signature: string; // unsigned | valid | invalid | present (no key)
}

export interface PreflightResult {
  ok: boolean;
  pipeline: string;
  errors: string[];
  warnings: string[];
}

// ── Queries ────────────────────────────────────────────────────────────────────

/** GET /projects/{projectId}/certificates/{runId} — the full certificate JSON. */
export const useCertificate = (projectId: string | null, runId: string | null) =>
  useQuery<Record<string, unknown>>({
    queryKey: ["certificates", projectId, runId],
    queryFn: async () => {
      const { data } = await executionClient.get(
        `/projects/${projectId}/certificates/${runId}`
      );
      return data;
    },
    enabled: !!projectId && !!runId,
  });

// ── Mutations ──────────────────────────────────────────────────────────────────

/** POST /projects/{projectId}/certificates/{runId}/verify — tamper + signature check. */
export const useVerifyCertificate = () =>
  useMutation({
    mutationFn: async ({ projectId, runId }: { projectId: string; runId: string }) => {
      const { data } = await executionClient.post<CertificateVerifyResult>(
        `/projects/${projectId}/certificates/${runId}/verify`
      );
      return data;
    },
  });

/**
 * POST /projects/{projectId}/pipelines/{name}/preflight — deep validation
 * (importable node functions, signatures, I/O keys, DAG) without executing.
 */
export const usePreflightPipeline = () =>
  useMutation({
    mutationFn: async ({
      projectId,
      pipelineName,
      env = "base",
    }: {
      projectId: string;
      pipelineName: string;
      env?: string;
    }) => {
      const { data } = await executionClient.post<PreflightResult>(
        `/projects/${projectId}/pipelines/${pipelineName}/preflight`,
        undefined,
        { params: { env }, timeout: 200_000 }
      );
      return data;
    },
  });
