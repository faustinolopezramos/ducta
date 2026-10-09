import { useEffect, useRef } from "react";
import type { Monaco, OnMount } from "@monaco-editor/react";
import { useDebugStore } from "./debugStore";

type Editor = Parameters<OnMount>[0];

/**
 * Breakpoints in a Python editor's margin: click beside a line to set or clear
 * one (kept per project and file); the line a debug run is stopped on is
 * highlighted, with the run's frame there.
 */
export function useBreakpointGutter(editor: Editor | null, monaco: Monaco | null, projectId: string | null, file: string | undefined) {
  const lines = useDebugStore((s) => (projectId && file ? s.breakpoints[projectId]?.[file] : undefined));
  const stoppedLine = useDebugStore((s) => {
    if (s.status !== "stopped" || s.projectId !== projectId) return null;
    const f = s.frames.find((fr) => fr.id === s.activeFrame);
    return f && f.inProject && f.file === file ? f.line : null;
  });
  const ids = useRef<string[]>([]);

  useEffect(() => {
    if (!editor || !monaco || !projectId || !file) return;
    editor.updateOptions({ glyphMargin: true });
    const sub = editor.onMouseDown((e: any) => {
      if (e.target?.type !== monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN) return;
      const line = e.target.position?.lineNumber;
      if (line) useDebugStore.getState().toggleBreakpoint(projectId, file, line);
    });
    return () => sub.dispose();
  }, [editor, monaco, projectId, file]);

  useEffect(() => {
    if (!editor || !monaco) return;
    const decorations = [
      ...(lines ?? []).map((line) => ({
        range: new monaco.Range(line, 1, line, 1),
        options: { glyphMarginClassName: "bp-dot", glyphMarginHoverMessage: { value: "Breakpoint — click to remove" }, stickiness: 1 },
      })),
      ...(stoppedLine
        ? [{ range: new monaco.Range(stoppedLine, 1, stoppedLine, 1), options: { isWholeLine: true, className: "bp-stopped-line", glyphMarginClassName: "bp-stopped" } }]
        : []),
    ];
    ids.current = editor.deltaDecorations(ids.current, decorations);
    if (stoppedLine) editor.revealLineInCenterIfOutsideViewport(stoppedLine);
  }, [editor, monaco, lines, stoppedLine]);
}
