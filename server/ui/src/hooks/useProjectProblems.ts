import { useCallback, useEffect, useMemo, useRef } from "react";
import { useValidateProject, type Problem } from "../api/queries/problems";
import { flattenProblems, useProblemsStore } from "../store/problemsStore";

const DRAFT_DEBOUNCE_MS = 400;

/** Split one validation result into its checks, so each replaces only its own. */
function bySource(problems: Problem[]): Record<string, Problem[]> {
  const out: Record<string, Problem[]> = { config: [], code: [] };
  for (const p of problems) (out[p.source] ??= []).push(p);
  return out;
}

/**
 * The project's problems while you work: validated on open and after every
 * saved change (`version` moves), and — for a file being edited — against
 * the unsaved text, debounced, so the Problems panel and the editor's markers
 * follow the keystrokes.
 */
export function useProjectProblems(projectId: string | undefined, version: unknown) {
  const setProblems = useProblemsStore((s) => s.setProblems);
  const storeProject = useProblemsStore((s) => s.projectId);
  const sources = useProblemsStore((s) => s.bySource);
  const { mutate: validate, isPending } = useValidateProject();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const apply = useCallback(
    (pid: string, problems: Problem[]) => {
      for (const [source, list] of Object.entries(bySource(problems))) setProblems(pid, source, list);
    },
    [setProblems],
  );

  // On open and after each save: the project as it is on disk.
  useEffect(() => {
    if (!projectId) return;
    validate({ projectId }, { onSuccess: (r) => apply(projectId, r.problems) });
  }, [projectId, version, validate, apply]);

  /** The project as it would be with `files` (project-relative path → text) saved. */
  const validateDraft = useCallback(
    (files: Record<string, string>) => {
      if (!projectId) return;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        validate({ projectId, files }, { onSuccess: (r) => apply(projectId, r.problems) });
      }, DRAFT_DEBOUNCE_MS);
    },
    [projectId, validate, apply],
  );
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const problems = useMemo(
    () => (storeProject === projectId ? flattenProblems(sources) : []),
    [sources, storeProject, projectId],
  );
  return { problems, isChecking: isPending, validateDraft };
}
