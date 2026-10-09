import { create } from "zustand";
import type { Problem } from "../api/queries/problems";

/**
 * Every problem known for the open project, by the check that found it —
 * `config`+`code` (validation, as you type), `preflight` (Validate), `save`
 * (a write the server refused). Each source replaces only its own list.
 */
interface ProblemsState {
  projectId: string | null;
  bySource: Record<string, Problem[]>;
  setProblems: (projectId: string, source: string, problems: Problem[]) => void;
  clear: () => void;
}

export const useProblemsStore = create<ProblemsState>((set) => ({
  projectId: null,
  bySource: {},
  setProblems: (projectId, source, problems) =>
    set((s) => ({
      projectId,
      bySource: { ...(s.projectId === projectId ? s.bySource : {}), [source]: problems },
    })),
  clear: () => set({ projectId: null, bySource: {} }),
}));

const SEVERITY_ORDER: Record<string, number> = { error: 0, warning: 1, info: 2 };

/** All problems, errors first, then by file and line; duplicates across sources once. */
export function flattenProblems(bySource: Record<string, Problem[]>): Problem[] {
  const seen = new Set<string>();
  const all: Problem[] = [];
  for (const list of Object.values(bySource)) {
    for (const p of list) {
      const key = `${p.severity}|${p.file}|${p.line}|${p.message}`;
      if (seen.has(key)) continue;
      seen.add(key);
      all.push(p);
    }
  }
  return all.sort(
    (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3) ||
      (a.file ?? "").localeCompare(b.file ?? "") ||
      (a.line ?? 0) - (b.line ?? 0),
  );
}

export function countBySeverity(problems: Problem[]) {
  return {
    errors: problems.filter((p) => p.severity === "error").length,
    warnings: problems.filter((p) => p.severity === "warning").length,
  };
}

/** Node ids with an error or a warning — for marking them on the canvas and explorer. */
export function nodesWithProblems(problems: Problem[]): Map<string, "error" | "warning"> {
  const out = new Map<string, "error" | "warning">();
  for (const p of problems) {
    if (!p.node || p.severity === "info") continue;
    if (out.get(p.node) !== "error") out.set(p.node, p.severity);
  }
  return out;
}
