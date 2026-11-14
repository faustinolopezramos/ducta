import type { Monaco } from "@monaco-editor/react";
import { JsonRpcConnection } from "./jsonrpc";

type Model = ReturnType<Monaco["editor"]["createModel"]>;

/**
 * One language-server connection per project, shared by its open editors.
 * Documents are tracked by the server's `file://` URI; each maps back to the
 * Monaco model showing it, so diagnostics land on the right editor.
 */
export class LspSession {
  readonly ready: Promise<any>;
  refs = 0;
  readonly models = new Map<string, Model>();
  private versions = new Map<string, number>();

  constructor(
    readonly conn: JsonRpcConnection,
    readonly root: string,
    monaco: Monaco,
  ) {
    const rootUri = toFileUri(root);
    this.ready = conn
      .request("initialize", {
        processId: null,
        rootUri,
        workspaceFolders: [{ uri: rootUri, name: root.split("/").pop() }],
        capabilities: {
          textDocument: {
            synchronization: { didSave: false, dynamicRegistration: false },
            hover: { contentFormat: ["markdown", "plaintext"] },
            completion: { completionItem: { snippetSupport: false, documentationFormat: ["markdown", "plaintext"] } },
            definition: { linkSupport: false },
            publishDiagnostics: { relatedInformation: false },
          },
          workspace: { configuration: true, workspaceFolders: true },
        },
      })
      .then((result) => {
        conn.notify("initialized", {});
        return result;
      });
    conn.on("textDocument/publishDiagnostics", (p: { uri: string; diagnostics: LspDiagnostic[] }) => {
      const model = this.models.get(p.uri);
      if (!model || model.isDisposed()) return;
      monaco.editor.setModelMarkers(model, "lsp", p.diagnostics.map((d) => toMarker(monaco, d)));
    });
  }

  open(uri: string, model: Model) {
    this.models.set(uri, model);
    this.versions.set(uri, 1);
    void this.ready.then(() =>
      this.conn.notify("textDocument/didOpen", {
        textDocument: { uri, languageId: "python", version: 1, text: model.getValue() },
      }),
    );
  }

  change(uri: string, text: string) {
    const version = (this.versions.get(uri) ?? 1) + 1;
    this.versions.set(uri, version);
    void this.ready.then(() =>
      this.conn.notify("textDocument/didChange", { textDocument: { uri, version }, contentChanges: [{ text }] }),
    );
  }

  close(uri: string) {
    this.models.delete(uri);
    this.versions.delete(uri);
    if (!this.conn.closed) this.conn.notify("textDocument/didClose", { textDocument: { uri } });
  }

  uriOf(model: Model): string | undefined {
    for (const [uri, m] of this.models) if (m === model) return uri;
    return undefined;
  }
}

export interface LspDiagnostic {
  range: LspRange;
  severity?: number;
  message: string;
  source?: string;
  code?: string | number;
}
export interface LspRange {
  start: { line: number; character: number };
  end: { line: number; character: number };
}

export function toFileUri(path: string): string {
  return `file://${path.split("/").map(encodeURIComponent).join("/")}`;
}

/** LSP is 0-based; Monaco is 1-based. */
export function toMonacoRange(r: LspRange) {
  return {
    startLineNumber: r.start.line + 1,
    startColumn: r.start.character + 1,
    endLineNumber: r.end.line + 1,
    endColumn: r.end.character + 1,
  };
}

export function toMarker(monaco: Monaco, d: LspDiagnostic) {
  const severity = { 1: monaco.MarkerSeverity.Error, 2: monaco.MarkerSeverity.Warning, 3: monaco.MarkerSeverity.Info, 4: monaco.MarkerSeverity.Hint }[d.severity ?? 1] ?? monaco.MarkerSeverity.Error;
  return {
    ...toMonacoRange(d.range),
    severity,
    message: d.message,
    source: d.source ?? "lsp",
    code: d.code != null ? String(d.code) : undefined,
  };
}

/** Hover contents in any of LSP's shapes, as markdown strings. */
export function hoverMarkdown(contents: unknown): string[] {
  const fence = (lang: string, value: string) => "```" + lang + "\n" + value + "\n```";
  const one = (c: any): string => {
    if (typeof c === "string") return c;
    if (c?.language) return fence(c.language, c.value);
    if (c?.kind === "plaintext") return fence("python", String(c.value ?? ""));
    return String(c?.value ?? "");
  };
  const list = Array.isArray(contents) ? contents : [contents];
  return list.map(one).filter(Boolean);
}
