import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import type { Monaco, OnMount } from "@monaco-editor/react";
import client from "../../api/client";
import { qk } from "../../api/queryKeys";
import { projectIdFromPath } from "../../utils/routes";
import { ruff, type RuffDiagnostic } from "./ruff";

type Editor = Parameters<OnMount>[0];

const LINT_DEBOUNCE_MS = 300;

/**
 * Ruff in a Python editor: diagnostics as markers while typing, its fixes as
 * quick fixes (⌘.), and "Format document" (⇧⌥F) — with the project's own
 * `[tool.ruff]` settings.
 */
export function useRuff({
  enabled,
  editor,
  monaco,
  code,
}: {
  enabled: boolean;
  editor: Editor | null;
  monaco: Monaco | null;
  code: string;
}) {
  const { pathname } = useLocation();
  const projectId = projectIdFromPath(pathname) ?? "";
  const { data: settings } = useQuery<Record<string, unknown>>({
    queryKey: [...qk.projects.detail(projectId), "ruff-config"],
    queryFn: () => client.get(`/projects/${projectId}/ruff-config`).then((r) => r.data),
    enabled: enabled && !!projectId,
    staleTime: 5 * 60 * 1000,
  });
  const diagnostics = useRef<RuffDiagnostic[]>([]);

  useEffect(() => {
    if (enabled && settings) void ruff.configure(settings);
  }, [enabled, settings]);

  // Lint, debounced.
  useEffect(() => {
    const model = editor?.getModel?.();
    if (!enabled || !editor || !monaco || !model) return;
    const timer = setTimeout(() => {
      ruff
        .check(code)
        .then((found) => {
          diagnostics.current = found;
          monaco.editor.setModelMarkers(
            model,
            "ruff",
            found.map((d) => ({
              startLineNumber: d.start_location.row,
              startColumn: d.start_location.column,
              endLineNumber: d.end_location.row,
              endColumn: d.end_location.column,
              message: d.code ? `${d.code} ${d.message}` : d.message,
              severity: d.code === null || d.code?.startsWith("E9") ? monaco.MarkerSeverity.Error : monaco.MarkerSeverity.Warning,
              source: "ruff",
            })),
          );
        })
        .catch(() => monaco.editor.setModelMarkers(model, "ruff", []));
    }, LINT_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [enabled, editor, monaco, code]);

  // Quick fixes and Format, on this editor's model only.
  useEffect(() => {
    const model = editor?.getModel?.();
    if (!enabled || !editor || !monaco || !model) return;
    const actions = monaco.languages.registerCodeActionProvider("python", {
      provideCodeActions: (target: { uri: { toString(): string } }, range: { startLineNumber: number; endLineNumber: number }) => {
        if (target.uri.toString() !== model.uri.toString()) return { actions: [], dispose: () => {} };
        const fixes = diagnostics.current.filter(
          (d) => d.fix && d.start_location.row <= range.endLineNumber && d.end_location.row >= range.startLineNumber,
        );
        return {
          actions: fixes.map((d) => ({
            title: `Ruff: ${d.fix!.message ?? `fix ${d.code}`}`,
            kind: "quickfix",
            isPreferred: true,
            edit: {
              edits: d.fix!.edits.map((e) => ({
                resource: model.uri,
                versionId: model.getVersionId(),
                textEdit: {
                  range: new monaco.Range(e.location.row, e.location.column, e.end_location.row, e.end_location.column),
                  text: e.content ?? "",
                },
              })),
            },
          })),
          dispose: () => {},
        };
      },
    });
    const format = editor.addAction({
      id: "ducta.ruff.format",
      label: "Format document (Ruff)",
      keybindings: [monaco.KeyMod.Shift | monaco.KeyMod.Alt | monaco.KeyCode.KeyF],
      contextMenuGroupId: "1_modification",
      run: async () => {
        const source = model.getValue();
        const formatted = await ruff.format(source).catch(() => null);
        if (formatted == null || formatted === source) return;
        // One edit, so ⌘Z takes the whole format back.
        editor.executeEdits("ruff-format", [{ range: model.getFullModelRange(), text: formatted }]);
      },
    });
    return () => {
      actions.dispose();
      format.dispose();
    };
  }, [enabled, editor, monaco]);
}
