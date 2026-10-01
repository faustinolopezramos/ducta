import { useQuery } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

// ─────────────────────────────────────────────
// NODE SCHEMA
// ─────────────────────────────────────────────

export interface NodeSchemaIO {
  id: string;
  name: string;
  declared: boolean;
  format?: string | null;
  path?: string | null;
  write_mode?: string | null;
  schema?: string | null;
  layer?: "bronze" | "silver" | "gold" | null;
  description?: string | null;
}

export interface NodeSchema {
  name: string;
  node_id: string;
  type: string;
  module: string;
  fn: string;
  description?: string | null;
  inputs: NodeSchemaIO[];
  outputs: NodeSchemaIO[];
  dependencies: string[];
  file_path: string;
  file_size_bytes?: number | null;
  file_exists: boolean;
  quality?: {
    check_count: number;
    gate_behavior?: string | null;
    is_sanity: boolean;
    /** Every enabled check, sanity and quality — the three fields above describe one block. */
    checks?: NodeQualityCheck[];
    /** Gates declared on either block (a gate without `enabled` still counts). */
    gates?: NodeQualityGate[];
  } | null;
  last_execution_status?: string | null;
  last_execution_time?: string | null;
  last_execution_duration?: number | null;
  last_execution_error_message?: string | null;
}

export interface PipelineNodeSchema {
  project_id: string;
  pipeline_name: string;
  node: NodeSchema;
}

/**
 * GET /projects/{projectId}/pipelines/{pipeline}/nodes/{node}/schema
 *
 * The node's full detail: datasets resolved against the registry, source-file
 * state, quality checks and gate, and the last run. This endpoint existed for
 * a long time and nothing called it, which is why the inspector could only
 * show a name and an invented format.
 */
export const useNodeSchema = (projectId: string, pipeline: string, node: string) =>
  useQuery<PipelineNodeSchema>({
    queryKey: qk.projects.nodeSchema(projectId, pipeline, node),
    queryFn: () =>
      client
        .get(`/projects/${projectId}/pipelines/${pipeline}/nodes/${node}/schema`)
        .then((r) => r.data),
    staleTime: 15 * 1000,
    enabled: !!projectId && !!pipeline && !!node,
  });

export interface NodeQualityCheck {
  name: string;
  /** `sanity` runs before the node reads its inputs; `quality` after it writes. */
  phase: "sanity" | "quality";
  params: Record<string, unknown>;
}

export interface NodeQualityGate {
  phase: "sanity" | "quality";
  behavior?: string | null;
  params: Record<string, unknown>;
}

export interface PipelineRunSummary {
  execution_id: string;
  status: string;
  time?: string | null;
  duration?: number | null;
  error_message?: string | null;
}

export interface PipelineNodeSchemas {
  project_id: string;
  pipeline_name: string;
  nodes: NodeSchema[];
  last_execution?: PipelineRunSummary | null;
}

/**
 * GET /projects/{projectId}/pipelines/{pipeline}/nodes/schema
 *
 * Every node of the pipeline with the same detail as `useNodeSchema`, plus the
 * pipeline's latest run — one request for the canvas, the contract list and the
 * focus panel instead of one per node.
 */
export const usePipelineNodeSchemas = (projectId: string, pipeline: string) =>
  useQuery<PipelineNodeSchemas>({
    queryKey: qk.projects.nodeSchemas(projectId, pipeline),
    queryFn: () =>
      client
        .get(`/projects/${projectId}/pipelines/${pipeline}/nodes/schema`)
        .then((r) => r.data),
    staleTime: 15 * 1000,
    enabled: !!projectId && !!pipeline,
  });
