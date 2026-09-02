import { useState, useEffect, useMemo, useRef, type ReactNode } from "react";
import Editor, { type Monaco, type OnMount } from "@monaco-editor/react";

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
  IconX,
} from "@tabler/icons-react";
import { colors } from "../theme/tokens";
import { Button } from "./ui";

interface CodeEditorProps {
  value: string;
  onSave?: (newCode: string) => void;
  onCancel?: () => void;
  onDirtyChange?: (isDirty: boolean) => void;
  readOnly?: boolean;
  height?: string;
  language?: string;
  filePath?: string;
  isSaving?: boolean;
  /** Optional inline validator. Runs debounced and renders Monaco markers. */
  validate?: (value: string) => EditorMarker[];
  /** Notified after each validation pass with the resulting markers. */
  onValidate?: (markers: EditorMarker[]) => void;
}

export function CodeEditor({
  value,
  onSave,
  onCancel,
  onDirtyChange,
  readOnly = false,
  height = "400px",
  language = "python",
  filePath,
  isSaving = false,
  validate,
  onValidate,
}: CodeEditorProps) {
  const [editedCode, setEditedCode] = useState(value);
  const [isDirty, setIsDirty] = useState(false);
  const [wordWrap, setWordWrap] = useState(true);
  const [minimap, setMinimap] = useState(false);
  const [cursor, setCursor] = useState({ line: 1, column: 1 });
  const [editorReady, setEditorReady] = useState(false);
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

  // Reload the buffer when the file changes. Adjusted during render rather
  // than in an effect: an effect let the editor paint one frame showing the
  // previous file's contents against the new file's path.
  const [loadedValue, setLoadedValue] = useState(value);
  if (value !== loadedValue) {
    setLoadedValue(value);
    setEditedCode(value);
    setIsDirty(false);
  }

  const handleChange = (newValue: string | undefined) => {
    setEditedCode(newValue || "");
    setIsDirty(newValue !== value);
  };

  const handleSave = () => {
    if (!onSave || readOnly || !isDirty) return;
    onSave?.(editedCode);
    setIsDirty(false);
  };

  useEffect(() => {
    handleSaveRef.current = handleSave;
  });

  const handleCancel = () => {
    setEditedCode(value);
    setIsDirty(false);
    onCancel?.();
  };

  const handleMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
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
  };

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

  // Determine if we're in dark mode
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  const theme = isDark ? "vs-dark" : "vs-light";

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
                fontSize: 12,
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
                  fontSize: 10,
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
          fontSize: 11,
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
        fontSize: 11,
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
