import client from "../../api/client";

/** Best-effort fallback: find the project that owns a pipeline by name.
 *  Older MLOps runs only record the pipeline's name; newer runs carry a
 *  project_id tag, so this scan is only needed for pre-tag runs. */
export async function findProjectForPipeline(pipelineName: string): Promise<string | null> {
  const { data } = await client.get("/projects");
  for (const project of data?.projects ?? []) {
    try {
      const { data: pipelinesData } = await client.get(`/projects/${project.id}/pipelines`);
      if (pipelinesData?.pipelines && pipelineName in pipelinesData.pipelines) {
        return project.id;
      }
    } catch {
      // skip unreadable project
    }
  }
  return null;
}

// ── Style helpers ─────────────────────────────────────────────────────────────

/** Colors for model lifecycle stages — not an execution Status, so this
 * feeds `Badge`'s `color` prop rather than `StatusBadge`. */
export const STAGE_COLOR: Record<string, string> = {
  Staging: "var(--warning)",
  Production: "var(--success)",
  Archived: "var(--text-muted)",
};

export function formatDate(iso?: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
