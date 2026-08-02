/**
 * projectAdapter.ts
 *
 * Converts between the server-persisted WorkspaceProject (from the API)
 * and the client-side ProjectItem (used by the Zustand reducer).
 *
 * WorkspaceProject is the source of truth (persisted in Git via the API).
 * ProjectItem is the in-memory "enriched view" that holds the full pipeline
 * graph for the current session. Pipelines are loaded on-demand per project.
 */
import type { WorkspaceProject } from "../types";
import type { ProjectItem } from "../store/reducer";

/**
 * Converts a server WorkspaceProject into a client ProjectItem.
 * Pipelines start empty — they are loaded on-demand when the user
 * navigates into a project (via useServerProjectPipelines).
 */
export function serverProjectToItem(sp: WorkspaceProject): ProjectItem {
  return {
    id: sp.id,
    name: sp.name,
    description: sp.description,
    pipelines: [],   // Loaded on-demand per project route
    connections: [],
    globalSettings: {
      environment: (sp.metadata?.environment as string) ?? "base",
      mode:        (sp.metadata?.mode        as string) ?? "local",
      layer:       (sp.metadata?.layer       as string) ?? "silver_layer",
    },
    createdAt: sp.created_at,
    updatedAt: sp.updated_at,
  };
}
