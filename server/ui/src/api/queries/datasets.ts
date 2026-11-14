import { useQuery } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

// ─────────────────────────────────────────────
// DATASET QUERIES
// ─────────────────────────────────────────────

export interface DatasetEndpoint {
  node: string;
  pipeline?: string | null;
}

/**
 * A dataset with its `input_config` / `output_config` entry resolved.
 * Every nullable field is null when the registry does not declare it — an
 * answer, not a gap to fill with a default.
 */
export interface ProjectDataset {
  name: string;
  layer?: "bronze" | "silver" | "gold" | null;
  format?: string | null;
  path?: string | null;
  write_mode?: string | null;
  schema?: string | null;
  options?: Record<string, unknown> | null;
  declared_in: string[];
  producers: DatasetEndpoint[];
  consumers: DatasetEndpoint[];
  description?: string | null;
  /** The catalog entry's metadata: owner, tags, sla, pii, criticality, docs… */
  metadata?: Record<string, unknown>;
}

export interface ProjectDatasets {
  project_id: string;
  datasets: ProjectDataset[];
  count: number;
}

/**
 * GET /projects/{projectId}/datasets
 * The project's dataset registry: format, path, write mode, schema, plus the
 * node that produces each dataset and every node that consumes it.
 */
export const useProjectDatasets = (projectId: string) =>
  useQuery<ProjectDatasets>({
    queryKey: qk.projects.datasets(projectId),
    queryFn: () =>
      client.get(`/projects/${projectId}/datasets`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!projectId,
  });
