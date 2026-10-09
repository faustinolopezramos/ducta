import { useState, useRef, lazy, Suspense } from "react";
const CodeEditor = lazy(() => import("./CodeEditor").then(m => ({ default: m.CodeEditor })));
import { colors, styles } from "../theme/tokens";
import { useDialogA11y } from "../hooks/useDialogA11y";

interface FileNode {
  id: string;
  name: string;
  type: "file" | "folder";
  path: string;
  expanded?: boolean;
  children?: FileNode[];
  content?: string;
}

interface CodeEditorModalProps {
  nodeName: string;
  moduleModule: string;
  functionName: string;
  code: string;
  onClose: () => void;
  onSave: (newCode: string) => void;
}

export function CodeEditorModal({
  nodeName,
  moduleModule,
  functionName,
  code,
  onClose,
  onSave,
}: CodeEditorModalProps) {
  const [selectedFile, setSelectedFile] = useState<string>("main.py");
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set(["src"]));
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogA11y(dialogRef, onClose);

  // Simple file tree structure based on module path
  const moduleParts = moduleModule.split(".");
  const files: FileNode[] = [
    {
      id: "src",
      name: "src",
      type: "folder",
      path: "src",
      expanded: true,
      children: moduleParts.map((part, idx) => {
        const parentPath = moduleParts.slice(0, idx).join("/");
        const fullPath = parentPath ? `${parentPath}/${part}` : part;
        const isLast = idx === moduleParts.length - 1;
        return {
          id: fullPath,
          name: isLast ? `${part}.py` : part,
          type: isLast ? "file" : "folder",
          path: fullPath,
          expanded: isLast ? false : idx < moduleParts.length - 1,
          children: isLast ? [] : undefined,
        };
      }),
    },
  ];

  const toggleFolder = (id: string) => {
    const newExpanded = new Set(expandedFolders);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedFolders(newExpanded);
  };

  const tintDanger = (e: { currentTarget: HTMLElement }) => {
    e.currentTarget.style.color = colors.danger;
  };
  const tintDefault = (e: { currentTarget: HTMLElement }) => {
    e.currentTarget.style.color = colors.text;
  };
  const hoverOn = (e: { currentTarget: HTMLElement }) => {
    e.currentTarget.style.backgroundColor = colors.surface;
  };
  const hoverOff = (e: { currentTarget: HTMLElement }, isSelected: boolean) => {
    e.currentTarget.style.backgroundColor = isSelected
      ? colors.surfaceElevated
      : "transparent";
  };

  const renderFileTree = (nodes: FileNode[], level = 0) => {
    return nodes.map((node) => (
      <div key={node.id}>
        <button
          type="button"
          onClick={() => {
            if (node.type === "folder") {
              toggleFolder(node.id);
            } else {
              setSelectedFile(node.path);
            }
          }}
          aria-expanded={node.type === "folder" ? expandedFolders.has(node.id) : undefined}
          aria-current={selectedFile === node.path ? "true" : undefined}
          style={{
            ...styles.resetButton,
            paddingLeft: `${level * 16 + 8}px`,
            padding: `6px ${level * 16 + 8}px`,
            backgroundColor:
              selectedFile === node.path ? colors.surfaceElevated : "transparent",
            color: selectedFile === node.path ? colors.primary : colors.text,
            fontSize: "12px",
            display: "flex",
            alignItems: "center",
            gap: "6px",
            borderLeft: `2px solid ${
              selectedFile === node.path ? colors.primary : "transparent"
            }`,
            transition: "all 0.15s",
            userSelect: "none",
          }}
          // Focus mirrors hover: a row that highlights for the mouse must
          // highlight for the keyboard too.
          onMouseOver={hoverOn}
          onFocus={hoverOn}
          onMouseOut={(e) => hoverOff(e, selectedFile === node.path)}
          onBlur={(e) => hoverOff(e, selectedFile === node.path)}
        >
          {node.type === "folder" ? (
            <>
              <span style={{ fontSize: "10px", width: "14px" }}>
                {expandedFolders.has(node.id) ? "▼" : "▶"}
              </span>
              <span>📁 {node.name}</span>
            </>
          ) : (
            <>
              <span style={{ fontSize: "10px", width: "14px" }}></span>
              <span>📄 {node.name}</span>
            </>
          )}
        </button>
        {node.type === "folder" && expandedFolders.has(node.id) && node.children && (
          <div>{renderFileTree(node.children, level + 1)}</div>
        )}
      </div>
    ));
  };

  return (
    // Backdrop: a redundant convenience next to Escape (bound by
    // `useDialogA11y`) and the ✕ control, so it needs no key handler of its
    // own. `role="presentation"` marks it as scenery rather than a control.
    <div
      role="presentation"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: "rgba(0, 0, 0, 0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: "var(--z-modal)",
        backdropFilter: "blur(4px)",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Edit code: ${nodeName}`}
        tabIndex={-1}
        style={{
          backgroundColor: colors.bg,
          borderRadius: "12px",
          width: "90vw",
          height: "90vh",
          maxWidth: "1400px",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 20px 60px rgba(0, 0, 0, 0.3)",
          overflow: "hidden",
          border: `1px solid ${colors.border}`,
          outline: "none",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 20px",
            borderBottom: `1px solid ${colors.border}`,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            backgroundColor: colors.surface,
          }}
        >
          <div>
            <h2 style={{ margin: "0 0 6px 0", fontSize: "16px", fontWeight: 600, color: colors.text }}>
              {nodeName}
            </h2>
            <p style={{ margin: 0, fontSize: "11px", color: colors.textMuted }}>
              Module: <code style={{ color: colors.primary }}>{moduleModule}</code> • Function:{" "}
              <code style={{ color: colors.primary }}>{functionName}</code>
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              fontSize: "20px",
              background: "none",
              border: "none",
              cursor: "pointer",
              color: colors.text,
              padding: "8px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transition: "color 0.2s",
            }}
            onMouseOver={tintDanger}
            onFocus={tintDanger}
            onMouseOut={tintDefault}
            onBlur={tintDefault}
          >
            ✕
          </button>
        </div>

        {/* Main Content */}
        <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
          {/* File Tree */}
          <div
            style={{
              width: "250px",
              borderRight: `1px solid ${colors.border}`,
              backgroundColor: colors.surface,
              overflowY: "auto",
              padding: "8px 0",
              userSelect: "none",
            }}
          >
            <div style={{ padding: "12px 8px 8px 8px" }}>
              <p
                style={{
                  fontSize: "10px",
                  fontWeight: 600,
                  textTransform: "uppercase",
                  color: colors.textMuted,
                  margin: "0 0 8px 0",
                  padding: "0 8px",
                }}
              >
                Explorer
              </p>
              {renderFileTree(files)}
            </div>
          </div>

            {/* Editor */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            {/* File Tab */}
            <div
              style={{
                padding: "12px 16px",
                borderBottom: `1px solid ${colors.border}`,
                backgroundColor: colors.bg,
                fontSize: "11px",
                color: colors.text,
              }}
            >
              <span style={{ color: colors.textMuted }}>Editing:</span>{" "}
              <code style={{ color: colors.primary, fontWeight: 600 }}>{selectedFile}</code>
            </div>

            {/* Editor Container */}
            <div style={{ flex: 1, overflow: "hidden" }}>
              <Suspense fallback={<div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: colors.textMuted }}>Loading editor...</div>}>
                <CodeEditor
                  value={code}
                  onSave={onSave}
                  onCancel={onClose}
                  height="100%"
                />
              </Suspense>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
