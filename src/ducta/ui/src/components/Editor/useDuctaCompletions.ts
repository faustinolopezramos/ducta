import { useEffect, useMemo } from "react";
import { useLocation } from "react-router-dom";
import type { Monaco } from "@monaco-editor/react";
import { useCodeIndex, useProjectDatasets } from "../../api/queries";
import { projectIdFromPath } from "../../utils/routes";

/** `src/silver.py` → `src.silver`. */
const moduleOf = (file: string) => file.replace(/\.py$/, "").replace(/\/__init__$/, "").split("/").join(".");

/** What completes where, in a pipeline YAML line, from the text before the cursor. */
export function yamlCompletionKind(before: string): "run" | "dataset" | null {
  if (/^\s*run:\s*[\w.:]*$/.test(before)) return "run";
  // A value: after `key: `, a `- ` item, or inside a flow `[a, b]` / `{alias: ds}`.
  if (/(^\s*-\s+|:\s+|[[,{]\s*)[\w.]*$/.test(before) && !/^\s*[\w.]*$/.test(before)) return "dataset";
  return null;
}

const PY_SNIPPETS = [
  {
    label: "dfn",
    detail: "A node function",
    insert: 'def ${1:transform}(${2:df}: DataFrame, **kwargs) -> DataFrame:\n    """${3:What it does.}"""\n    ${0:return $2}',
  },
  {
    label: "dlog",
    detail: "Log with loguru",
    insert: 'logger.info("${1:message} {}", ${2:value})',
  },
];

const YAML_SNIPPETS = [
  {
    label: "node",
    detail: "A transform node",
    insert: "${1:layer.name}:\n  description: ${2:What it does}\n  run: ${3:src.module:function}\n  inputs: {${4:alias}: ${5:dataset}}\n  outputs: [${6:dataset}]",
  },
  {
    label: "qcheck",
    detail: "Quality checks and a gate",
    insert: "quality:\n  checks:\n    row_count: {min: ${1:1}}\n    null_rate: {columns: [${2:id}], threshold: ${3:0.0}}\n  gate: {max_errors: ${4:0}}",
  },
  {
    label: "ingest",
    detail: "An ingest node (declarative JDBC)",
    insert: "${1:bronze.ingest_table}:\n  kind: ingest\n  ingest: {source: ${2:connection}, table: ${3:dbo.table}}\n  outputs: [${4:bronze.schema.table}]",
  },
];

/**
 * Completion that knows the project: in pipeline YAML, dataset names from the
 * catalog and `run:` targets from the source; in Python, dataset names inside
 * strings; snippets in both. Registered once per open editor, for its model.
 */
export function useDuctaCompletions(monaco: Monaco | null, modelUri: string | null, language: string) {
  const { pathname } = useLocation();
  const projectId = projectIdFromPath(pathname) ?? "";
  const { data: datasetsData } = useProjectDatasets(projectId);
  const { data: index } = useCodeIndex(projectId);
  const datasets = useMemo(() => (datasetsData?.datasets ?? []).map((d) => d.name), [datasetsData]);
  const functions = useMemo(
    () => Object.entries(index?.files ?? {}).flatMap(([file, fns]) => fns.map((f) => ({ run: `${moduleOf(file)}:${f.name}`, params: f.params }))),
    [index],
  );

  useEffect(() => {
    if (!monaco || !modelUri || (language !== "yaml" && language !== "python")) return;
    const { CompletionItemKind, CompletionItemInsertTextRule } = monaco.languages;
    const provider = monaco.languages.registerCompletionItemProvider(language, {
      triggerCharacters: [" ", ":", ".", '"', "'", "[", ","],
      provideCompletionItems: (model: any, position: any) => {
        if (model.uri.toString() !== modelUri) return { suggestions: [] };
        const before: string = model.getLineContent(position.lineNumber).slice(0, position.column - 1);
        const word = model.getWordUntilPosition(position);
        const token = /[\w.:]*$/.exec(before)?.[0] ?? "";
        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: position.column - token.length,
          endColumn: word.endColumn,
        };
        const snippetRange = { ...range, startColumn: word.startColumn };
        const snippets = (language === "yaml" ? YAML_SNIPPETS : PY_SNIPPETS).map((s) => ({
          label: s.label,
          kind: CompletionItemKind.Snippet,
          detail: s.detail,
          insertText: s.insert,
          insertTextRules: CompletionItemInsertTextRule.InsertAsSnippet,
          range: snippetRange,
        }));
        if (language === "yaml") {
          const kind = yamlCompletionKind(before);
          if (kind === "run") {
            return {
              suggestions: functions.map((f) => ({
                label: f.run,
                kind: CompletionItemKind.Function,
                detail: `(${f.params.join(", ")})`,
                insertText: f.run,
                range,
              })),
            };
          }
          if (kind === "dataset") {
            return {
              suggestions: datasets.map((d) => ({ label: d, kind: CompletionItemKind.Value, detail: "dataset", insertText: d, range })),
            };
          }
          return { suggestions: snippets };
        }
        // Python: datasets inside a string, snippets elsewhere.
        const inString = (before.match(/["']/g) ?? []).length % 2 === 1;
        if (inString) {
          return {
            suggestions: datasets.map((d) => ({ label: d, kind: CompletionItemKind.Value, detail: "dataset", insertText: d, range })),
          };
        }
        return { suggestions: snippets };
      },
    });
    return () => provider.dispose();
  }, [monaco, modelUri, language, datasets, functions]);
}
