import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import type { Monaco, OnMount } from "@monaco-editor/react";
import client from "../../../api/client";
import { apiWebSocketUrl } from "../../../hooks/wsUtils";
import { StorageService } from "../../../utils/storage";
import { normalizeSourceInput } from "../../../utils/sourcePath";
import { projectIdFromPath, routes } from "../../../utils/routes";
import { JsonRpcConnection } from "./jsonrpc";
import { hoverMarkdown, LspSession, toFileUri, toMonacoRange } from "./session";

type Editor = Parameters<OnMount>[0];
type Model = NonNullable<ReturnType<Editor["getModel"]>>;
type Position = { lineNumber: number; column: number };

interface LspStatus {
  available: boolean;
  command?: string | null;
  root: string;
  hint?: string | null;
}

const sessions = new Map<string, LspSession>();
let providersFor: Monaco | null = null;
let openFile: ((path: string, line: number) => void) | null = null;

function sessionOf(model: Model): { session: LspSession; uri: string } | null {
  for (const session of sessions.values()) {
    const uri = session.uriOf(model);
    if (uri) return { session, uri };
  }
  return null;
}

function acquire(projectId: string, root: string, monaco: Monaco): LspSession {
  let session = sessions.get(projectId);
  if (!session || session.conn.closed) {
    let url = apiWebSocketUrl(`ws/projects/${encodeURIComponent(projectId)}/lsp`);
    try {
      const source = normalizeSourceInput(StorageService.getSource());
      if (source) url += `?source=${encodeURIComponent(source)}`;
    } catch {
      /* no source chosen: the server falls back to DUCTA_WORKSPACE */
    }
    const conn = new JsonRpcConnection(new WebSocket(url) as any);
    session = new LspSession(conn, root, monaco);
    conn.on("$close", () => sessions.get(projectId) === session && sessions.delete(projectId));
    sessions.set(projectId, session);
  }
  session.refs += 1;
  return session;
}

function release(projectId: string, session: LspSession) {
  session.refs -= 1;
  if (session.refs <= 0) {
    session.conn.close();
    if (sessions.get(projectId) === session) sessions.delete(projectId);
  }
}

/** Hover, completion and go-to-definition for Python, answered by whichever session has the model. */
function registerProviders(monaco: Monaco) {
  if (providersFor === monaco) return;
  providersFor = monaco;
  const at = (position: Position) => ({ line: position.lineNumber - 1, character: position.column - 1 });

  monaco.languages.registerHoverProvider("python", {
    provideHover: async (model: Model, position: Position) => {
      const s = sessionOf(model);
      if (!s) return null;
      const r = await s.session.conn
        .request("textDocument/hover", { textDocument: { uri: s.uri }, position: at(position) })
        .catch(() => null);
      if (!r?.contents) return null;
      return {
        contents: hoverMarkdown(r.contents).map((value) => ({ value })),
        range: r.range ? toMonacoRange(r.range) : undefined,
      };
    },
  });

  monaco.languages.registerCompletionItemProvider("python", {
    triggerCharacters: ["."],
    provideCompletionItems: async (model: Model, position: Position) => {
      const s = sessionOf(model);
      if (!s) return { suggestions: [] };
      const r = await s.session.conn
        .request("textDocument/completion", { textDocument: { uri: s.uri }, position: at(position) })
        .catch(() => null);
      const items: any[] = Array.isArray(r) ? r : r?.items ?? [];
      const word = model.getWordUntilPosition(position);
      const range = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn };
      return {
        suggestions: items.slice(0, 200).map((it) => ({
          label: it.label,
          // LSP CompletionItemKind is 1-based and close to Monaco's order, offset by one.
          kind: typeof it.kind === "number" ? Math.max(it.kind - 1, 0) : monaco.languages.CompletionItemKind.Text,
          insertText: it.insertText ?? it.label,
          detail: it.detail,
          documentation: typeof it.documentation === "string" ? it.documentation : it.documentation?.value,
          sortText: it.sortText,
          range,
        })),
      };
    },
  });

  monaco.languages.registerDefinitionProvider("python", {
    provideDefinition: async (model: Model, position: Position) => {
      const s = sessionOf(model);
      if (!s) return null;
      const r = await s.session.conn
        .request("textDocument/definition", { textDocument: { uri: s.uri }, position: at(position) })
        .catch(() => null);
      const first = Array.isArray(r) ? r[0] : r;
      const uri: string | undefined = first?.uri ?? first?.targetUri;
      const range = first?.range ?? first?.targetSelectionRange;
      if (!uri || !range) return null;
      if (uri === s.uri) return { uri: model.uri, range: toMonacoRange(range) };
      // Another file of the project: open it in the code view at that line.
      const rootUri = toFileUri(s.session.root);
      if (uri.startsWith(rootUri + "/") && openFile) {
        openFile(decodeURIComponent(uri.slice(rootUri.length + 1)), range.start.line + 1);
      }
      return null;
    },
  });
}

/**
 * A real Python language server in the editor — types, hover, completion,
 * go-to-definition and diagnostics — when the API has one (basedpyright,
 * pyright or pylsp). Without one this does nothing, and Ruff still lints.
 */
export function useLanguageServer({
  enabled,
  editor,
  monaco,
  filePath,
}: {
  enabled: boolean;
  editor: Editor | null;
  monaco: Monaco | null;
  /** The file's path inside the project, e.g. `src/silver.py`. */
  filePath?: string;
}) {
  const projectId = projectIdFromPath(useLocation().pathname);
  const navigate = useNavigate();
  const { data: status } = useQuery<LspStatus>({
    queryKey: ["server-projects", projectId, "lsp"],
    queryFn: () => client.get(`/projects/${projectId}/lsp`).then((r) => r.data),
    enabled: enabled && !!projectId,
    staleTime: Infinity,
    retry: false,
  });
  const on = enabled && !!status?.available && !!editor && !!monaco && !!filePath && !!projectId;
  const root = status?.root;

  useEffect(() => {
    openFile = (path, line) => projectId && navigate(routes.code(projectId, path, line));
  }, [navigate, projectId]);

  useEffect(() => {
    if (!on || !root) return;
    const model = editor!.getModel();
    if (!model) return;
    registerProviders(monaco!);
    const session = acquire(projectId!, root, monaco!);
    const uri = toFileUri(`${root.replace(/\/+$/, "")}/${filePath!.replace(/^\/+/, "")}`);
    session.open(uri, model);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const sub = model.onDidChangeContent(() => {
      clearTimeout(timer);
      timer = setTimeout(() => session.change(uri, model.getValue()), 250);
    });
    return () => {
      clearTimeout(timer);
      sub.dispose();
      if (!model.isDisposed()) monaco!.editor.setModelMarkers(model, "lsp", []);
      session.close(uri);
      release(projectId!, session);
    };
  }, [on, root, editor, monaco, filePath, projectId]);

  return { available: !!status?.available, command: status?.command ?? null, hint: status?.hint ?? null };
}
