import { useState, useEffect, useMemo, useRef, type ReactNode } from "react";
import Editor, { type Monaco, type OnMount } from "@monaco-editor/react";
import { defineDuctaTheme } from "./Editor/monacoSetup";
import { useProjectSchema } from "./Editor/useProjectSchema";
import { useRuff } from "./Editor/useRuff";
import { useDuctaCompletions } from "./Editor/useDuctaCompletions";
import { useLanguageServer } from "./Editor/lsp/useLanguageServer";
import { useYamlNavigation } from "./Editor/useYamlNavigation";
import { useGitGutter } from "./Editor/useGitGutter";
import { useEditorBuffer } from "./Editor/useEditorBuffer";
import { useBreakpointGutter } from "./Debug/useBreakpointGutter";
import { projectIdFromPath } from "../utils/routes";

/** A lightweight, monaco-agnostic marker the parent can emit from `validate`. */
export interface EditorMarker {
  startLineNumber: number;
  startColumn?: number;
  endLineNumber?: number;
  endColumn?: number;
  message: string;
  severity: "error" | "warning" | "info";
}
import {
  IconCheck,
  IconDeviceFloppy,
  IconFileCode,
  IconMap,
  IconTextWrap,
  IconWand,
  IconX,
} from "@tabler/icons-react";
import { colors } from "../theme/tokens";
import { Button } from "./ui";

interface CodeEditorProps {
  value: string;
  /** What was typed in this file before, to show instead of `value` (it reads unsaved). */
  draft?: string;
  /** A returned promise that rejects puts the editor back to "Unsaved". */
  onSave?: (newCode: string) => void | Promise<unknown>;
  onCancel?: () => void;
  onDirtyChange?: (isDirty: boolean) => void;
  readOnly?: boolean;
  height?: string;
  language?: string;
  filePath?: string;
  /** The file's path in the git repository (workspace-relative) — turns on the git gutter and blame. */
  gitPath?: string;
  isSaving?: boolean;
  /** Optional inline validator. Runs debounced and renders Monaco markers. */
  validate?: (value: string) => EditorMarker[];
  /** Notified after each validation pass with the resulting markers. */
  onValidate?: (markers: EditorMarker[]) => void;
  /** Scroll to and highlight this 1-based line (e.g. a node's function). */
  revealLine?: number;
  /** Clickable annotations above lines — "◆ node · ▶ Run · Show in graph". */
  codeLenses?: EditorCodeLens[];
  /** Extra controls in the header, before the word-wrap/minimap toggles. */
  headerActions?: ReactNode;
  /** The live editor, for callers that add their own Monaco behaviour. */
  onEditorReady?: (editor: Parameters<OnMount>[0], monaco: Monaco) => void;
  /** Every edit, as typed — for validating a draft elsewhere (debounce there). */
  onChangeValue?: (value: string) => void;
  /** Markers computed elsewhere (e.g. by the server), shown beside `validate`'s own. */
  markers?: EditorMarker[];
  /** ⌘⏎: run what this file is (a node, on a sample). */
  onRun?: () => void;
}

/** One code lens: a line and the actions shown above it. */
export interface EditorCodeLens {
  line: number;
  items: { title: string; onClick?: () => void }[];
}

export function CodeEditor({
  value,
  draft,
  onSave,
  onCancel,
  onDirtyChange,
  readOnly = false,
  height = "400px",
  language = "python",
  filePath,
  gitPath,
  isSaving = false,
  validate,
  onValidate,
  revealLine,
  codeLenses,
  headerActions,
  onEditorReady,
  onChangeValue,
  markers,
  onRun,
}: CodeEditorProps) {
  useProjectSchema();
  const buffer = useEditorBuffer(value, filePath, draft);
  const editedCode = buffer.text;
  const isDirty = buffer.isDirty;
  // Code is read by its indentation: wrapping Python broke expressions across
  // lines with no number. Prose-like files (YAML, Markdown) still wrap.
  const [wordWrap, setWordWrap] = useState(language !== "python" && language !== "sql");
  const [minimap, setMinimap] = useState(false);
  const [cursor, setCursor] = useState({ line: 1, column: 1 });
  const [editorReady, setEditorReady] = useState(false);
  // The live editor as state, for hooks that need it during render (Ruff).
  const [instance, setInstance] = useState<{ editor: Parameters<OnMount>[0]; monaco: Monaco } | null>(null);
  const handleSaveRef = useRef<() => void>(() => {});
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const monacoRef = useRef<Monaco | null>(null);
  const onValidateRef = useRef(onValidate);
  // Written in an effect, not during render: the ref is only read from
  // effects and callbacks that run later, so post-commit is soon enough,
  // and a render-phase write is not safe under concurrent rendering.
  useEffect(() => {
    onValidateRef.current = onValidate;
  });

  const lineCount = useMemo(() => editedCode.split("\n").length, [editedCode]);
  const fileName = filePath?.split("/").filter(Boolean).pop() ?? inferFileName(language);

  // Notify parent when dirty state changes
  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  const handleChange = (newValue: string | undefined) => {
    buffer.setText(newValue || "");
    onChangeValue?.(newValue || "");
  };

  const handleSave = () => {
    if (!onSave || readOnly || !isDirty) return;
    buffer.markSaved(editedCode, onSave(editedCode));
  };

  useEffect(() => {
    handleSaveRef.current = handleSave;
  });

  const handleCancel = () => {
    buffer.revert();
    onCancel?.();
  };

  const handleMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    setInstance({ editor, monaco });
    setEditorReady(true);

    const disposable = editor.onDidChangeCursorPosition((event: { position: { lineNumber: number; column: number } }) => {
      setCursor({
        line: event.position.lineNumber,
        column: event.position.column,
      });
    });

    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      handleSaveRef.current();
    });

    editor.onDidDispose(() => disposable.dispose());
    onEditorReady?.(editor, monaco);
  };

  // Python: Ruff lint as you type, its fixes as quick fixes, ⇧⌥F to format.
  const isPython = language === "python";
  useRuff({
    enabled: isPython && !readOnly && editorReady,
    editor: instance?.editor ?? null,
    monaco: instance?.monaco ?? null,
    code: editedCode,
  });
  // …and a real language server (types, hover, go-to-definition) when the API has one.
  const lsp = useLanguageServer({
    enabled: isPython && !readOnly && editorReady,
    editor: instance?.editor ?? null,
    monaco: instance?.monaco ?? null,
    filePath,
  });
  // YAML: hover a dataset, node or module:function; ⌘-click goes to it.
  useYamlNavigation(instance?.monaco ?? null, language === "yaml" && editorReady);
  // Git: changed-line bars in the margin and blame on the cursor's line.
  useGitGutter(instance?.editor ?? null, instance?.monaco ?? null, readOnly ? undefined : gitPath);
  // Python: breakpoints in the margin; the line a debug run stopped on.
  useBreakpointGutter(
    instance?.editor ?? null,
    instance?.monaco ?? null,
    isPython ? projectIdFromPath(window.location.pathname) : null,
    filePath,
  );
  // ⌘⏎ runs — through a ref, so the command always calls the latest handler.
  const onRunRef = useRef(onRun);
  useEffect(() => {
    onRunRef.current = onRun;
  });
  const canRun = Boolean(onRun);
  useEffect(() => {
    if (!instance || !canRun) return;
    const { editor, monaco } = instance;
    const action = editor.addAction({
      id: "ducta.run-sample",
      label: "Run this node on a sample",
      keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
      run: () => onRunRef.current?.(),
    });
    return () => action.dispose();
  }, [instance, canRun]);

  useDuctaCompletions(
    instance?.monaco ?? null,
    instance?.editor.getModel()?.uri.toString() ?? null,
    language,
  );
  const formatDocument = () => {
    editorRef.current?.getAction?.("ducta.ruff.format")?.run();
  };

  // Markers from outside (server validation), under their own owner so they
  // never clobber the ones `validate` sets.
  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    const model = editor?.getModel?.();
    if (!editorReady || !monaco || !model) return;
    const severity = (s: EditorMarker["severity"]) =>
      s === "error" ? monaco.MarkerSeverity.Error : s === "warning" ? monaco.MarkerSeverity.Warning : monaco.MarkerSeverity.Info;
    monaco.editor.setModelMarkers(
      model,
      "ducta-external",
      (markers ?? []).map((m) => ({
        startLineNumber: m.startLineNumber,
        startColumn: m.startColumn ?? 1,
        endLineNumber: m.endLineNumber ?? m.startLineNumber,
        endColumn: m.endColumn ?? model.getLineMaxColumn(Math.min(m.startLineNumber, model.getLineCount())),
        message: m.message,
        severity: severity(m.severity),
      })),
    );
  }, [editorReady, markers]);

  // Bring a line into view and mark it — the function a node runs.
  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (!editorReady || !editor || !monaco || !revealLine) return;
    // A few lines of context above, so the code lens over the line shows too.
    editor.setScrollTop(editor.getTopForLineNumber(Math.max(1, revealLine - 3)));
    editor.setPosition({ lineNumber: revealLine, column: 1 });
    const decorations = editor.createDecorationsCollection([
      {
        range: new monaco.Range(revealLine, 1, revealLine, 1),
        options: { isWholeLine: true, className: "ducta-editor-revealed-line" },
      },
    ]);
    return () => decorations.clear();
  }, [editorReady, revealLine, filePath, value]);

  // Code lenses. Monaco registers providers per language, so this one answers
  // only for this editor's model, and its commands live on this editor.
  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    const model = editor?.getModel?.();
    if (!editorReady || !editor || !monaco || !model || !codeLenses?.length) return;
    const commands: { dispose(): void }[] = [];
    const lenses = codeLenses.flatMap((lens, li) =>
      lens.items.map((item, ii) => {
        let id = "";
        if (item.onClick) {
          id = `ducta.lens.${editor.getId()}.${li}.${ii}.${Date.now()}`;
          commands.push(monaco.editor.registerCommand(id, () => item.onClick?.()));
        }
        return { line: lens.line, title: item.title, id };
      }),
    );
    const provider = monaco.languages.registerCodeLensProvider(model.getLanguageId(), {
      provideCodeLenses: (target: { uri: { toString(): string } }) => ({
        lenses:
          target.uri.toString() === model.uri.toString()
            ? lenses.map((l, i) => ({
                range: new monaco.Range(l.line, 1, l.line, 1),
                id: `ducta-lens-${i}`,
                command: { id: l.id, title: l.title },
              }))
            : [],
        dispose: () => {},
      }),
    });
    return () => {
      provider.dispose();
      commands.forEach((c) => c.dispose());
    };
  }, [editorReady, codeLenses]);

  // Debounced inline validation → Monaco markers. No-op when no validator given.
  useEffect(() => {
    if (!validate || !editorReady) return;
    const handle = setTimeout(() => {
      const editor = editorRef.current;
      const monaco = monacoRef.current;
      const model = editor?.getModel?.();
      if (!editor || !monaco || !model) return;

      const markers = validate(editedCode);
      const severityFor = (s: EditorMarker["severity"]) =>
        s === "error"
          ? monaco.MarkerSeverity.Error
          : s === "warning"
            ? monaco.MarkerSeverity.Warning
            : monaco.MarkerSeverity.Info;

      monaco.editor.setModelMarkers(
        model,
        "ducta",
        markers.map((m) => ({
          startLineNumber: m.startLineNumber,
          startColumn: m.startColumn ?? 1,
          endLineNumber: m.endLineNumber ?? m.startLineNumber,
          endColumn: m.endColumn ?? 1000,
          message: m.message,
          severity: severityFor(m.severity),
        })),
      );
      onValidateRef.current?.(markers);
    }, 500);
    return () => clearTimeout(handle);
  }, [editedCode, validate, editorReady]);

  // The app's own colours, light or dark. Defined once per theme, not per
  // render: redefining the active theme re-applies it to every editor, and
  // this renders on each keystroke.
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  const theme = useMemo(() => defineDuctaTheme(isDark), [isDark]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height,
        minHeight: 0,
        border: `1px solid ${colors.border}`,
        borderRadius: 8,
        overflow: "hidden",
        background: colors.surfaceElevated,
      }}
    >
      <div
        style={{
          height: 40,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "0 10px 0 12px",
          borderBottom: `1px solid ${colors.border}`,
          background: colors.surface,
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 9, minWidth: 0 }}>
          <IconFileCode size={16} stroke={1.8} color={colors.textMuted} />
          <div style={{ minWidth: 0 }}>
            <div
              title={filePath ?? fileName}
              style={{
                color: colors.text,
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-xs)",
                lineHeight: "16px",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                maxWidth: 460,
              }}
            >
              {fileName}
            </div>
            {filePath && (
              <div
                title={filePath}
                style={{
                  color: colors.textDim,
                  fontFamily: "var(--font-mono)",
                  fontSize: "var(--text-2xs)",
                  lineHeight: "12px",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  maxWidth: 460,
                }}
              >
                {filePath}
              </div>
            )}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          {headerActions}
          {isPython && !readOnly && (
            <span
              className={`code-editor__lsp${lsp.available ? " is-on" : ""}`}
              title={lsp.available ? `Types, hover and go-to-definition by ${lsp.command}` : lsp.hint ?? "No Python language server"}
            >
              {lsp.available ? lsp.command?.replace(/-langserver$/, "") : "no types"}
            </span>
          )}
          {isPython && !readOnly && (
            <IconButton title="Format document with Ruff (⇧⌥F)" active={false} onClick={formatDocument}>
              <IconWand size={15} stroke={1.9} />
            </IconButton>
          )}
          <EditorPill tone={isDirty ? "warning" : "success"}>
            {isDirty ? "Unsaved" : "Saved"}
          </EditorPill>
          <IconButton
            title={wordWrap ? "Disable word wrap" : "Enable word wrap"}
            active={wordWrap}
            onClick={() => setWordWrap((v) => !v)}
          >
            <IconTextWrap size={15} stroke={1.9} />
          </IconButton>
          <IconButton
            title={minimap ? "Hide minimap" : "Show minimap"}
            active={minimap}
            onClick={() => setMinimap((v) => !v)}
          >
            <IconMap size={15} stroke={1.9} />
          </IconButton>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        <Editor
          height="100%"
          language={language}
          // The model's URI: the YAML language server picks the schema by it.
          path={filePath ? `file:///${filePath.replace(/^\/+/, "")}` : undefined}
          value={editedCode}
          onChange={handleChange}
          onMount={handleMount}
          theme={theme}
          options={{
            minimap: { enabled: minimap, side: "right", scale: 1 },
            lineNumbers: "on",
            wordWrap: wordWrap ? "on" : "off",
            formatOnPaste: true,
            formatOnType: true,
            readOnly: readOnly,
            fontSize: 13,
            fontFamily: "var(--font-mono)",
            lineHeight: 20,
            tabSize: 2,
            padding: { top: 12, bottom: 12 },
            automaticLayout: true,
            bracketPairColorization: { enabled: true },
            cursorBlinking: "smooth",
            folding: true,
            glyphMargin: true,
            renderLineHighlight: "all",
            scrollBeyondLastLine: false,
          }}
        />
      </div>

      <div
        style={{
          minHeight: 34,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "5px 10px 5px 12px",
          borderTop: `1px solid ${colors.border}`,
          background: colors.surface,
          color: colors.textMuted,
          fontSize: "var(--text-2xs)",
          fontFamily: "var(--font-mono)",
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
          <span>{language}</span>
          <span>{lineCount} lines</span>
          <span>
            Ln {cursor.line}, Col {cursor.column}
          </span>
        </div>

        {!readOnly && onSave && (
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {onCancel && (
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<IconX size={14} stroke={2} />}
                onClick={handleCancel}
                disabled={isSaving}
                title="Discard changes"
              >
                Cancel
              </Button>
            )}
            <Button
              variant="primary"
              size="sm"
              leftIcon={isDirty ? <IconDeviceFloppy size={14} stroke={2} /> : <IconCheck size={14} stroke={2} />}
              onClick={handleSave}
              disabled={!isDirty || isSaving}
              loading={isSaving}
              title="Save changes (Cmd/Ctrl+S)"
            >
              {isSaving ? "Saving" : "Save"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function inferFileName(language: string) {
  if (language === "yaml" || language === "yml") return "pipeline.yml";
  if (language === "json") return "data.json";
  if (language === "toml") return "config.toml";
  return "node.py";
}

function EditorPill({ children, tone }: { children: string; tone: "success" | "warning" }) {
  const color = tone === "success" ? colors.success : colors.warning;
  const background = tone === "success" ? colors.greenA10 : colors.amberA10;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        height: 22,
        padding: "0 8px",
        borderRadius: 999,
        border: `1px solid ${tone === "success" ? colors.greenA20 : colors.amberA20}`,
        background,
        color,
        fontSize: "var(--text-2xs)",
        fontWeight: 600,
        fontFamily: "var(--font-sans)",
      }}
    >
      {children}
    </span>
  );
}

function IconButton({
  title,
  active,
  onClick,
  children,
}: {
  title: string;
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-pressed={active}
      onClick={onClick}
      style={{
        width: 28,
        height: 28,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: 6,
        border: `1px solid ${active ? colors.accentA30 : colors.border}`,
        background: active ? colors.accentBg : "transparent",
        color: active ? colors.accent : colors.textMuted,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}
