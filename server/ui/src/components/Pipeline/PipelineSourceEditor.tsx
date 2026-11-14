import { lazy, Suspense, useMemo } from "react";
import { IconAlertTriangle, IconCircleCheck, IconCircleX } from "@tabler/icons-react";
import {
  problemsFromError,
  usePipelineSource,
  useSavePipelineSource,
  type Problem,
} from "../../api/queries/problems";
import { useProblemsStore } from "../../store/problemsStore";
import type { EditorMarker } from "../CodeEditor";
import { Skeleton } from "../ui/Skeleton";

const CodeEditor = lazy(() => import("../CodeEditor").then((m) => ({ default: m.CodeEditor })));

interface PipelineSourceEditorProps {
  projectId: string;
  pipelineId: string;
  /** The project's problems; those in this file become markers. */
  problems: Problem[];
  /** Validate the unsaved text (debounced by the caller). */
  onDraft: (files: Record<string, string>) => void;
  revealLine?: number;
}

/**
 * The YAML lens: the pipeline's own file — the one people also edit by hand,
 * comments and all — validated as you type against the project's schema
 * (in the editor) and the whole project (on the server). Saving writes the
 * text as given and keeps it only if the project still validates.
 */
export function PipelineSourceEditor({ projectId, pipelineId, problems, onDraft, revealLine }: PipelineSourceEditorProps) {
  const { data: source, isLoading } = usePipelineSource(projectId, pipelineId);
  const { mutate: save, isPending } = useSavePipelineSource();
  const setProblems = useProblemsStore((s) => s.setProblems);

  const mine = useMemo(() => problems.filter((p) => source && p.file === source.file), [problems, source]);
  const markers = useMemo<EditorMarker[]>(
    () =>
      mine
        .filter((p) => p.line)
        .map((p) => ({ startLineNumber: p.line!, startColumn: p.column ?? 1, message: p.message, severity: p.severity })),
    [mine],
  );
  const errors = mine.filter((p) => p.severity === "error").length;
  const warnings = mine.filter((p) => p.severity === "warning").length;

  if (isLoading || !source) {
    return (
      <div className="pipeline-yaml-editor">
        <Skeleton variant="block" height="100%" />
      </div>
    );
  }

  const onSave = (content: string) =>
    save(
      { projectId, name: pipelineId, content, expectedVersion: source.version },
      {
        onSuccess: () => setProblems(projectId, "save", []),
        onError: (err) => setProblems(projectId, "save", problemsFromError(err)),
      },
    );

  return (
    <div className="pipeline-yaml-editor">
      <div className="yaml-editor-header">
        <span className="yaml-editor-label">
          <span className="status-dot-small" />
          {source.file}
        </span>
        {errors > 0 ? (
          <span className="yaml-status yaml-status-error"><IconCircleX size={13} /> {errors} error{errors !== 1 ? "s" : ""}</span>
        ) : warnings > 0 ? (
          <span className="yaml-status yaml-status-warn"><IconAlertTriangle size={13} /> {warnings} warning{warnings !== 1 ? "s" : ""}</span>
        ) : (
          <span className="yaml-status yaml-status-ok"><IconCircleCheck size={13} /> Valid</span>
        )}
      </div>
      <div className="yaml-editor-body">
        <Suspense fallback={<Skeleton variant="block" height="100%" />}>
          <CodeEditor
            value={source.content}
            language="yaml"
            filePath={source.file}
            height="100%"
            onSave={onSave}
            isSaving={isPending}
            markers={markers}
            revealLine={revealLine}
            onChangeValue={(text) => onDraft({ [source.file]: text })}
          />
        </Suspense>
      </div>
    </div>
  );
}
