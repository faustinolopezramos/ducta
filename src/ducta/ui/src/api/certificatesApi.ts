/**
 * Run Certificates + deep preflight — API hooks.
 *
 * Every terminating run emits a tamper-evident Run Certificate; these hooks let
 * the UI list/inspect/verify them and run the same deep preflight as
 * `ducta config validate` before executing a pipeline.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { executionClient } from "./client";
import { qk } from "./queryKeys";

// ── Types (mirror ducta.api.routes.certificates / projects.PreflightResponse) ──

/** The six outcomes `verify_certificate`/`verify_certificate_data` can report. */
export type CertificateSignatureState =
  | "unsigned"
  | "valid"
  | "invalid"
  | "present (no key)"
  | "stripped"
  | "unverifiable";

export interface CertificateVerifyResult {
  ok: boolean;
  run_id?: string | null;
  reason: string;
  signature: CertificateSignatureState;
  /** What a passing result proves: self-hash only, or signature checked. */
  level?: "integrity" | "authenticated" | "none";
  /** False when the certificate was issued under evidence_level=signed and no key was supplied. */
  policy_satisfied?: boolean;
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
  /** true = same, false = differs, null = measured with different fingerprint
   *  algorithms (e.g. across a Ducta upgrade) — "not comparable", not a claim
   *  either way. Never render this as "unknown"/a warning. */
  match: boolean | null;
  not_comparable_reason?: string | null;
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
  /** false if any output's `match` is null — outputs_match/identical then only
   *  cover the subset that could actually be measured. */
  outputs_comparable: boolean;
  quality: CertificateDiffQualityRow[];
  /** The model each serving node scored with, side by side (schema >= 1.6). */
  models?: CertificateDiffModelRow[];
  models_match?: boolean;
  identical: boolean;
}

export interface CertificateDiffModelRow {
  node: string;
  model_a: string | null;
  model_b: string | null;
  match: boolean;
}

/** The registered model a serving/evaluation node scored with (schema >= 1.6). */
export interface CertificateServedModel {
  source: "ducta" | "mlflow";
  name: string;
  /** The version the run pinned — not the stage it asked for. */
  version: number;
  stage_at_resolution: string | null;
  uri: string;
  framework: string;
  artifact_sha256: string | null;
  /** "registry": matched the hash recorded at registration; "load": hashed on load. */
  hash_source: "registry" | "load" | null;
}

/** What an ML node was given and did — present only on ML nodes. */
export interface CertificateNodeML {
  stage: string | null;
  split: Record<string, unknown> | null;
  /** Where the split was declared. */
  split_source: "node" | "pipeline" | null;
  /** Whether the node was bound to apply it (its own split, or training/evaluation). */
  split_required: boolean;
  /** True only when the node really called split_dataframe with its ml_context. */
  split_applied: boolean;
  model_version: string | null;
  hyperparams: Record<string, unknown>;
  model?: CertificateServedModel;
}

export interface CertificateNode {
  name: string;
  type: string;
  status: string;
  duration_seconds: number;
  outputs: string[];
  error?: string | null;
  ml?: CertificateNodeML;
}

/** How strongly a dataset's fingerprint actually proves its content — the
 *  field that must never be buried in a UI. */
export type FingerprintMode = "exact" | "exact_crypto" | "sample" | "schema";

export interface CertificateDatasetFingerprint {
  input_key?: string;
  filepath?: string;
  file_size_bytes?: number | null;
  file_mtime?: string | null;
  schema_hash?: string | null;
  columns?: Record<string, string> | null;
  row_count?: number | null;
  sample_hash?: string | null;
  raw_file_hash?: string | null;
  content_hash?: string | null;
  fingerprint?: string;
  engine?: "spark" | "pandas" | "unknown";
  algorithm?: string;
  mode?: FingerprintMode;
  degraded_reason?: string | null;
  details?: Record<string, unknown> | null;
}

export interface CertificateQualityEntry {
  node: string;
  phase: "sanity" | "data_quality" | string;
  passed: boolean;
  score: number;
  errors: number;
  warnings: number;
  checks?: number;
  aborted?: boolean;
  reason?: string;
  gate?: string;
  triggered_rules?: string[];
}

export interface CertificateCodeNodeHash {
  source_hash?: string | null;
  module_hash?: string | null;
  module_file?: string | null;
  scope: "function" | "module" | "none";
  algorithm?: string;
  degraded_reason?: string | null;
}

export interface CertificateCodeBlock {
  nodes: Record<string, CertificateCodeNodeHash>;
  quality_extensions?: Record<string, string>;
}

export interface CertificateEnvironment {
  python_version?: string;
  os_info?: string;
  hostname?: string;
  ducta_version?: string;
  git_commit?: string | null;
  git_branch?: string | null;
  git_dirty?: boolean | null;
  pip_packages?: Record<string, string>;
  env_hash?: string;
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
  environment?: CertificateEnvironment;
  nodes: CertificateNode[];
  inputs: Record<string, CertificateDatasetFingerprint>;
  outputs: Record<string, CertificateDatasetFingerprint>;
  quality: CertificateQualityEntry[];
  code?: CertificateCodeBlock;
  error: string | null;
  evidence_complete?: boolean;
  evidence_gaps?: string[];
  signed?: boolean;
  certificate_hash: string;
  signature?: string | null;
  key_id?: string | null;
}

// ── Queries ────────────────────────────────────────────────────────────────────

/** GET /projects/{projectId}/certificates/{runId} — the full certificate JSON. */
export const useCertificate = (projectId: string | null, runId: string | null) =>
  useQuery<RunCertificate>({
    queryKey: qk.certificates.detail(projectId, runId),
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
    queryKey: qk.certificates.diff(projectId, runId, otherRunId),
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
 * POST /certificates/verify — standalone verification, no project/execution
 * context required. Takes the certificate's raw JSON text directly (a paste
 * or a file's contents) plus an optional shared signing key, so a certificate
 * handed to you by someone else's Ducta instance can be checked on its own
 * terms. Deliberately unauthenticated on the server; nothing here assumes a
 * logged-in session.
 */
export const useVerifyCertificateStandalone = () =>
  useMutation({
    mutationFn: async ({
      certificateJson,
      signingKey,
    }: {
      certificateJson: string;
      signingKey?: string;
    }) => {
      const { data } = await executionClient.post<CertificateVerifyResult>(
        `/certificates/verify`,
        { certificate_json: certificateJson, signing_key: signingKey || null }
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
