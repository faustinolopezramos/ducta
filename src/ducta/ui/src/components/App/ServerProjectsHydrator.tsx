import { useEffect, useRef } from "react";
import { useServerProjects } from "../../api/queries";
import { useProjectStore } from "../../store/projectStore";
import { serverProjectToItem } from "../../utils/projectAdapter";
import type { ProjectItem } from "../../store/reducer";

/**
 * On app boot (with a valid source), fetches server-persisted projects and
 * adds any missing from the local reducer — e.g. projects created from
 * another client session or from the CLI. Prevents duplicates.
 */
export function ServerProjectsHydrator({ localProjects }: { localProjects: ProjectItem[] }) {
  const { data } = useServerProjects();
  const dispatch = useProjectStore((s) => s.dispatch);
  const localProjectsRef = useRef(localProjects);
  // Written in an effect, not during render: the ref is only read from
  // effects and callbacks that run later, so post-commit is soon enough,
  // and a render-phase write is not safe under concurrent rendering.
  useEffect(() => {
    localProjectsRef.current = localProjects;
  });

  useEffect(() => {
    if (!data?.projects?.length) return;
    const localIds = new Set(localProjectsRef.current.map((p) => p.id));
    for (const sp of data.projects) {
      if (!localIds.has(sp.id)) {
        dispatch({ type: "ADD_PROJECT", payload: serverProjectToItem(sp) });
      }
    }
  }, [data, dispatch]);

  return null;
}
