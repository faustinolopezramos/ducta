import { useMemo } from "react";
import { useNodes, useServerProjectPipelines, useServerProjects } from "../api/queries";
import { pipelinesFromServer } from "../utils/pipelineAdapter";
import { toProjectSummary } from "../utils/projectAdapter";
import type { Pipeline, ProjectSummary } from "../types";

/**
 * The workspace's projects, straight from the query cache.
 *
 * Replaces the Zustand copy that a hydrator used to sync with `useEffect`:
 * two sources of truth, and an undo history that could "restore" a project
 * the server had already deleted.
 */
/** A project's display name for its id — the id itself when the project is unknown. */
export function useProjectName(): (id: string | null | undefined) => string {
  const { projects } = useProjectList();
  return (id) => (id ? (projects.find((p) => p.id === id)?.name ?? id) : "—");
}

export function useProjectList(): {
  projects: ProjectSummary[];
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
} {
  const { data, isLoading, error, refetch } = useServerProjects();
  const projects = useMemo(() => (data?.projects ?? []).map(toProjectSummary), [data]);
  // `error` is passed on: without it a failed listing read as "no projects yet".
  return { projects, isLoading, error, refetch: () => void refetch() };
}

/**
 * A project's pipelines, with each node resolved against the workspace's node
 * specs — derived on read, so a save anywhere (this tab, another tab, the CLI)
 * shows up as soon as the query refetches.
 *
 * `raw` is the server response itself (specs by name + the `commit_sha` to
 * pass back for optimistic concurrency).
 */
export function useProjectPipelines(projectId: string | undefined) {
  const query = useServerProjectPipelines(projectId ?? "");
  const { data: nodesData } = useNodes();
  const pipelines = useMemo<Pipeline[]>(
    () => pipelinesFromServer(query.data?.pipelines ?? {}, nodesData?.nodes ?? {}),
    [query.data, nodesData]
  );
  return { pipelines, raw: query.data, isLoading: query.isLoading, error: query.error };
}
