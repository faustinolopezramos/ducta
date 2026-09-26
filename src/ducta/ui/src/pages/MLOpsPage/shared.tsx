import { useQuery } from "@tanstack/react-query";
import client from "../../api/client";
import { qk } from "../../api/queryKeys";

/** Walks every project's pipeline list, calling `visit` for each pipeline
 *  found. Shared by `findProjectForPipeline` (matches by name, any pipeline
 *  type) and `listMlPipelines` (filters to type=="ml") so the GET /projects
 *  → GET /projects/{id}/pipelines double-fetch lives in exactly one place. */
async function forEachProjectPipeline(
  visit: (projectId: string, projectName: string, pipelineName: string, spec: any) => void
): Promise<void> {
  const { data } = await client.get("/projects");
  await Promise.all(
    (data?.projects ?? []).map(async (project: any) => {
      try {
        const { data: pipelinesData } = await client.get(`/projects/${project.id}/pipelines`);
        for (const [name, spec] of Object.entries<any>(pipelinesData?.pipelines ?? {})) {
          visit(project.id, project.name ?? project.id, name, spec);
        }
      } catch {
        // skip unreadable project
      }
    })
  );
}

/** Best-effort fallback: find the project that owns a pipeline by name.
 *  Older MLOps runs only record the pipeline's name; newer runs carry a
 *  project_id tag, so this scan is only needed for pre-tag runs. Matches by
 *  name regardless of pipeline type — a rerun target predates this file's
 *  ml-only filtering, so narrowing this to type=="ml" would silently break
 *  rerun for any older non-ml-tagged run. */
export async function findProjectForPipeline(pipelineName: string): Promise<string | null> {
  let found: string | null = null;
  await forEachProjectPipeline((projectId, _projectName, name) => {
    if (name === pipelineName) found = projectId;
  });
  return found;
}

export interface MlPipelineOption {
  projectId: string;
  projectName: string;
  pipelineName: string;
}

/** Every `type=="ml"` pipeline across every project the connected workspace
 *  can see, flattened for the MLOps page's combined Pipeline picker —
 *  MLOps has no cross-pipeline aggregation on the backend (each pipeline's
 *  experiment tracker/model registry is a fully separate store), so this is
 *  the only way to browse "which pipeline" without knowing its name upfront. */
export async function listMlPipelines(): Promise<MlPipelineOption[]> {
  const out: MlPipelineOption[] = [];
  await forEachProjectPipeline((projectId, projectName, pipelineName, spec) => {
    if (spec?.type === "ml") out.push({ projectId, projectName, pipelineName });
  });
  return out;
}

export function useMlPipelineOptions() {
  return useQuery<MlPipelineOption[]>({
    queryKey: qk.mlops.mlPipelines(),
    queryFn: listMlPipelines,
    staleTime: 60 * 1000,
  });
}

// ── Style helpers ─────────────────────────────────────────────────────────────

/** Colors for model lifecycle stages — not an execution Status, so this
 * feeds `Badge`'s `color` prop rather than `StatusBadge`. */
export const STAGE_COLOR: Record<string, string> = {
  Staging: "var(--warning)",
  Production: "var(--success)",
  Archived: "var(--text-muted)",
};
