import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import client from "../../api/client";
import { qk } from "../../api/queryKeys";
import { projectIdFromPath } from "../../utils/routes";
import { setProjectSchema, type ProjectSchema } from "./monacoSetup";

/** Feed the open project's format-2 schema to the YAML language server. */
export function useProjectSchema() {
  const { pathname } = useLocation();
  const projectId = projectIdFromPath(pathname) ?? "";
  const { data } = useQuery<ProjectSchema>({
    queryKey: qk.projects.schema(projectId),
    queryFn: () => client.get(`/projects/${projectId}/schema`).then((r) => r.data),
    staleTime: Infinity,
    enabled: !!projectId,
  });
  useEffect(() => {
    if (data?.$defs) setProjectSchema(data);
  }, [data]);
}
