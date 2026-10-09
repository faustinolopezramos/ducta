import { useQuery } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

export interface CodeFunction {
  name: string;
  line: number;
  params: string[];
  docstring?: string | null;
}

/** One node that runs project code, and where its function is. */
export interface CodeIndexNode {
  node: string;
  pipeline?: string | null;
  module: string;
  function: string;
  /** Relative to the project root. */
  file: string;
  /** Relative to the workspace root — what /workspace/files reads and writes. */
  workspace_file: string;
  /** Line of `def <function>`; null when the function is not in the file. */
  line?: number | null;
  exists: boolean;
  params: string[];
  inputs: Record<string, string>;
}

export interface CodeIndex {
  nodes: CodeIndexNode[];
  files: Record<string, CodeFunction[]>;
}

/**
 * GET /projects/{projectId}/code-index
 * Node → function → file:line for the whole project, from the syntax tree
 * (no project code is imported). Drives node ↔ code navigation.
 */
export const useCodeIndex = (projectId: string) =>
  useQuery<CodeIndex>({
    queryKey: qk.projects.codeIndex(projectId),
    queryFn: () => client.get(`/projects/${projectId}/code-index`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!projectId,
  });

/** The nodes a project file runs, by function name. */
export function nodesByFunction(index: CodeIndex | undefined, file: string): Map<string, CodeIndexNode[]> {
  const out = new Map<string, CodeIndexNode[]>();
  for (const entry of index?.nodes ?? []) {
    if (entry.file !== file && entry.workspace_file !== file) continue;
    const list = out.get(entry.function) ?? [];
    list.push(entry);
    out.set(entry.function, list);
  }
  return out;
}
