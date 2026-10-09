import { useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Monaco, OnMount } from "@monaco-editor/react";
import client from "../../api/client";
import { useGitAvailable, useGitWorkingDiff } from "../../api/queries";
import { formatRelative } from "../../utils/timeLabels";
import { diffLines, gutterMarks } from "./lineDiff";

type Editor = Parameters<OnMount>[0];

interface BlameLine {
  line_number: number;
  sha: string;
  author: string;
  timestamp: string;
}

/**
 * Git in the editor's margins: a bar beside each line added or changed since
 * the last commit (a wedge where lines were deleted), and — on the cursor's
 * line — who last changed it and when, as it was committed.
 */
export function useGitGutter(editor: Editor | null, monaco: Monaco | null, filePath: string | undefined) {
  // Nothing to mark without a repository: asking anyway was a 409 per file opened.
  const gitPath = useGitAvailable() ? filePath : undefined;
  const { data: head } = useGitWorkingDiff(gitPath ?? null);
  const { data: blame } = useQuery<{ lines: BlameLine[] }>({
    queryKey: ["git", "blame", gitPath],
    queryFn: () => client.get(`/git/blame/${gitPath}`, { expectedStatuses: [409] }).then((r) => r.data),
    enabled: !!gitPath,
    staleTime: 30 * 1000,
    retry: false,
  });
  const base = head?.original;
  const byCommittedLine = useMemo(() => new Map((blame?.lines ?? []).map((l) => [l.line_number, l])), [blame]);
  const ids = useRef<string[]>([]);
  const blameIds = useRef<string[]>([]);

  useEffect(() => {
    if (!editor || !monaco || base == null) return;
    const model = editor.getModel();
    if (!model) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let toCommitted = new Map<number, number>();

    const paint = () => {
      const text = model.getValue();
      const marks = base === "" ? [] : gutterMarks(base, text);
      ids.current = editor.deltaDecorations(
        ids.current,
        marks.map((m) => ({
          range: new monaco.Range(m.from, 1, m.to, 1),
          options: {
            isWholeLine: true,
            linesDecorationsClassName: `git-gutter git-gutter--${m.kind}`,
            overviewRuler: { color: m.kind === "added" ? "#2f9e6e" : m.kind === "modified" ? "#3b82c4" : "#d64545", position: monaco.editor.OverviewRulerLane.Left },
          },
        })),
      );
      // Current line → the committed line it still is, for blame.
      toCommitted = new Map();
      for (const op of diffLines(base.split("\n"), text.split("\n"))) if (op.kind === "equal") toCommitted.set(op.b + 1, op.a + 1);
      showBlame();
    };

    const showBlame = () => {
      const pos = editor.getPosition();
      const line = pos?.lineNumber;
      const committed = line ? toCommitted.get(line) : undefined;
      const info = committed ? byCommittedLine.get(committed) : undefined;
      blameIds.current = editor.deltaDecorations(
        blameIds.current,
        info && line
          ? [
              {
                range: new monaco.Range(line, model.getLineMaxColumn(line), line, model.getLineMaxColumn(line)),
                options: {
                  showIfCollapsed: true,
                  after: {
                    content: `    ${info.author}, ${formatRelative(info.timestamp) ?? info.timestamp} · ${info.sha.slice(0, 7)}`,
                    inlineClassName: "git-blame-inline",
                  },
                },
              },
            ]
          : [],
      );
    };

    paint();
    const subs = [
      model.onDidChangeContent(() => {
        clearTimeout(timer);
        timer = setTimeout(paint, 300);
      }),
      editor.onDidChangeCursorPosition(showBlame),
    ];
    return () => {
      clearTimeout(timer);
      subs.forEach((s) => s.dispose());
      ids.current = editor.deltaDecorations(ids.current, []);
      blameIds.current = editor.deltaDecorations(blameIds.current, []);
    };
  }, [editor, monaco, base, byCommittedLine]);
}
