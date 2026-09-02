/**
 * Run Certificates + deep preflight — API hooks.
 *
 * Every terminating run emits a tamper-evident Run Certificate; these hooks let
 * the UI list/inspect/verify them and run the same deep preflight as
 * `ducta config validate` before executing a pipeline.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { executionClient } from "./client";
import { sourceKey } from "./utils";

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

export interface CertificateDiffOutputRow {
  key: string;
  in_a: boolean;
  in_b: boolean;
  match: boolean;
}

export interface CertificateDiffQualityRow {
  node: string | null;
  phase: string | null;
  passed_a: boolean | null;
  passed_b: boolean | null;
  errors_a: number | null;
  errors_b: number | null;
  match: boolean;
}

/** Mirrors ducta.api.routes.certificates.CertificateDiffResponse. */
export interface CertificateDiffResult {
  run_a: string | null;
  run_b: string | null;
  pipeline_a: string | null;
  pipeline_b: string | null;
  pipeline_match: boolean;
  environment_match: boolean;
  status_a: string | null;
  status_b: string | null;
  status_match: boolean;
  config_fingerprint_match: boolean;
  outputs: CertificateDiffOutputRow[];
  outputs_match: boolean;
  quality: CertificateDiffQualityRow[];
  identical: boolean;
}

export interface CertificateNode {
  name: string;
  type: string;
  status: string;
  duration_seconds: number;
  outputs: string[];
  error: string | null;
}

export interface CertificateDatasetFingerprint {
  input_key?: string;
  filepath?: string;
  file_size_bytes?: number | null;
  file_mtime?: string | null;
  schema_hash?: string | null;
  row_count?: number | null;
  sample_hash?: string | null;
  fingerprint?: string;
}

export interface CertificateQualityEntry {
  node: string;
  phase: string;
  passed: boolean;
  score: number;
  errors: number;
  warnings: number;
  checks?: number;
  aborted?: boolean;
  reason?: string;
}

/** Mirrors ducta.core.certificate.RunCertificate. */
export interface RunCertificate {
  schema_version: string;
  run_id: string;
  pipeline: string;
  environment_name: string;
  status: string;
  started_at: string;
  ended_at: string;
  duration_seconds: number | null;
  ducta_version: string;
  config_fingerprint: string;
  nodes: CertificateNode[];
  inputs: Record<string, CertificateDatasetFingerprint>;
  outputs: Record<string, CertificateDatasetFingerprint>;
  quality: CertificateQualityEntry[];
  error: string | null;
  certificate_hash: string;
  signature?: string | null;
  key_id?: string | null;
}

// ── Queries ────────────────────────────────────────────────────────────────────

/** GET /projects/{projectId}/certificates/{runId} — the full certificate JSON. */
export const useCertificate = (projectId: string | null, runId: string | null) =>
  useQuery<RunCertificate>({
    queryKey: ["certificates", sourceKey(), projectId, runId],
    queryFn: async () => {
      const { data } = await executionClient.get(
        `/projects/${projectId}/certificates/${runId}`
      );
      return data;
    },
    enabled: !!projectId && !!runId,
  });

/**
 * GET /projects/{projectId}/certificates/{runId}/diff/{otherRunId} — compare
 * two certificates (config, outputs, quality). Used both for ad-hoc comparison
 * and to score a reproduction run against the certificate it was reproducing.
 */
export const useCertificateDiff = (
  projectId: string | null,
  runId: string | null,
  otherRunId: string | null
) =>
  useQuery<CertificateDiffResult>({
    queryKey: ["certificates", sourceKey(), "diff", projectId, runId, otherRunId],
    queryFn: async () => {
      const { data } = await executionClient.get(
        `/projects/${projectId}/certificates/${runId}/diff/${otherRunId}`
      );
      return data;
    },
    enabled: !!projectId && !!runId && !!otherRunId,
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
 * POST /projects/{projectId}/certificates/{runId}/reproduce — starts an async
 * re-run of the certificate's pipeline/environment. Returns the new execution
 * (pending); poll it with useExecutionStatus, then diff its certificate_run_id
 * against the original runId with useCertificateDiff.
 */
export const useReproduceCertificate = () =>
  useMutation({
    mutationFn: async ({
      projectId,
      runId,
      startDate,
      endDate,
    }: {
      projectId: string;
      runId: string;
      startDate?: string;
      endDate?: string;
    }) => {
      const { data } = await executionClient.post(
        `/projects/${projectId}/certificates/${runId}/reproduce`,
        { start_date: startDate || null, end_date: endDate || null }
      );
      return data as { id: string; status: string };
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
