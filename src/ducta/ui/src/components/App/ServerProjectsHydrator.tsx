import { useEffect } from "react";
import { useServerProjects } from "../../api/queries";
import { useProjectStore } from "../../store/projectStore";
import { serverProjectToItem } from "../../utils/projectAdapter";

/**
 * Keeps the local project list in step with the server's.
 *
 * Picks up projects created from another client session or from the CLI, and
 * refreshes the server-owned fields — notably the pipeline count — on projects
 * the store already has. It used to add only the missing ones, so a count went
 * stale the moment a pipeline was created and stayed stale until a reload;
 * reconciling in the reducer also means this no longer has to hold a ref to the
 * local list just to diff against it.
 */
export function ServerProjectsHydrator() {
  const { data } = useServerProjects();
  const dispatch = useProjectStore((s) => s.dispatch);

  useEffect(() => {
    if (!data?.projects?.length) return;
    dispatch({ type: "HYDRATE_PROJECTS", projects: data.projects.map(serverProjectToItem) });
  }, [data, dispatch]);

  return null;
}
