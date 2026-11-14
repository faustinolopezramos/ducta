import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import client from "../api/client";
import { qk } from "../api/queryKeys";
import type { Problem, PipelineSource } from "../api/queries/problems";
import type { WorkspaceProject } from "../types";

/**
 * The text with the fix applied: `old` → `new` on the problem's line when it is
 * there (as a whole word), else at its first whole-word occurrence. Null when
 * `old` is nowhere — the file changed since the problem was found.
 */
export function replaceInText(text: string, line: number | null | undefined, from: string, to: string): string | null {
  const word = new RegExp(`(^|[^\\w.-])${from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=$|[^\\w.-])`);
  const lines = text.split("\n");
  const at = line ? line - 1 : -1;
  if (at >= 0 && at < lines.length && word.test(lines[at])) {
    lines[at] = lines[at].replace(word, (_m, pre) => `${pre}${to}`);
    return lines.join("\n");
  }
  if (!word.test(text)) return null;
  return text.replace(word, (_m, pre) => `${pre}${to}`);
}

/** Apply a problem's fix to its file: through the pipeline-source API for a pipeline, the workspace file API otherwise. */
export function useApplyFix() {
  const queryClient = useQueryClient();
  return useCallback(
    async (projectId: string, p: Problem) => {
      if (!p.fix || !p.file) throw new Error("This problem has no fix to apply");
      const [from, to] = p.fix.replace;
      if (p.pipeline && p.file.startsWith("pipelines/")) {
        const src: PipelineSource = (await client.get(`/projects/${projectId}/pipelines/${p.pipeline}/source`)).data;
        const next = replaceInText(src.content, p.line, from, to);
        if (next == null) throw new Error(`'${from}' is no longer in ${p.file}`);
        await client.put(`/projects/${projectId}/pipelines/${p.pipeline}/source`, { content: next, expected_version: src.version });
      } else {
        const project: WorkspaceProject = (await client.get(`/projects/${projectId}`)).data;
        const path = [project.root, p.file].filter(Boolean).join("/");
        const { content } = (await client.get("/workspace/files/content", { params: { path } })).data;
        const next = replaceInText(content, p.line, from, to);
        if (next == null) throw new Error(`'${from}' is no longer in ${p.file}`);
        await client.put("/workspace/files/content", { path, content: next });
      }
      queryClient.invalidateQueries({ queryKey: qk.projects.all() });
      queryClient.invalidateQueries({ queryKey: qk.nodes.all() });
      queryClient.invalidateQueries({ queryKey: qk.files.all() });
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
    },
    [queryClient],
  );
}
