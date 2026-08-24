import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "./client";
import { sourceKey } from "./utils";
import { defaultOnError } from "./mutations/errors";

export interface TemplateInfo {
  type: string;
  name: string;
  description: string;
}

export interface GenerateFromTemplateVars {
  template: string;
  project_name: string;
  config_format?: "yaml" | "json" | "toml";
  include_sample_code?: boolean;
  sandbox_developers?: string[];
}

export interface GenerateFromTemplateResult {
  project_id: string;
  template: string;
  path: string;
}

export const useTemplates = () =>
  useQuery<TemplateInfo[]>({
    queryKey: ["templates", sourceKey()],
    queryFn: () => client.get("/templates").then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

export const useGenerateFromTemplate = () => {
  const qc = useQueryClient();
  return useMutation<GenerateFromTemplateResult, unknown, GenerateFromTemplateVars>({
    mutationFn: (vars) => client.post("/templates/generate", vars).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["server-projects"] });
    },
    onError: defaultOnError,
  });
};
