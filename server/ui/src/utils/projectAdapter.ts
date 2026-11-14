/**
 * projectAdapter.ts
 *
 * Converts the server-persisted WorkspaceProject (from the API) into the
 * ProjectSummary the dashboard renders. The server is the only source of
 * truth: this is a view of the query cache, never a copy kept in a store.
 */
import type { ProjectSummary, WorkspaceProject } from "../types";

export function toProjectSummary(sp: WorkspaceProject): ProjectSummary {
  return {
    id: sp.id,
    name: sp.name,
    description: sp.description,
    pipelineCount: sp.pipeline_count,
    createdAt: sp.created_at,
    updatedAt: sp.updated_at,
    configError: sp.config_status === "invalid" ? sp.config_error ?? "The configuration does not load" : null,
  };
}
