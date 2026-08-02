import { useState } from "react";
import {
  IconChevronDown,
  IconChevronRight,
  IconBrandPython,
  IconFile,
  IconFileTypeTxt,
  IconFolder,
  IconFolderOpen,
  IconPlus,
} from "@tabler/icons-react";
import { useWorkspaceFiles, type FileEntry } from "../api/queries";
import { useWriteWorkspaceFile } from "../api/mutations";
import { colors, styles } from "../theme/tokens";

interface FileTreeProps {
  activePath?: string;
  onSelectFile: (path: string) => void;
}

function FileIcon({ name }: { name: string }) {
  if (name.endsWith(".py")) return <IconBrandPython size={15} stroke={1.8} color={colors.accent} />;
  if (name.endsWith(".yaml") || name.endsWith(".yml")) return <IconFileTypeTxt size={15} stroke={1.8} color={colors.warning ?? "#f59e0b"} />;
  return <IconFile size={15} stroke={1.8} color={colors.textDim} />;
}

interface TreeNodeProps {
  entry: FileEntry;
  activePath?: string;
  depth: number;
  onSelectFile: (path: string) => void;
}

function TreeNode({ entry, activePath, depth, onSelectFile }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(depth === 0);
  const { data } = useWorkspaceFiles(entry.type === "dir" && expanded ? entry.path : undefined!);

  const isActive = entry.path === activePath;
  const indent = depth * 12 + 8;

  if (entry.type === "dir") {
    return (
      <div>
        <div
          onClick={() => setExpanded(v => !v)}
          title={entry.path}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 5,
            minHeight: 28,
            padding: `4px 8px 4px ${indent}px`,
            cursor: "pointer",
            color: colors.textMuted,
            fontSize: 12,
            ...styles.fontMono,
            userSelect: "none",
          }}
          onMouseOver={(e) => { e.currentTarget.style.background = colors.surfaceElevated ?? colors.surface; }}
          onMouseOut={(e) => { e.currentTarget.style.background = "transparent"; }}
        >
          <span style={{ width: 12, display: "flex", alignItems: "center", justifyContent: "center", color: colors.textDim }}>
            {expanded ? <IconChevronDown size={13} stroke={2} /> : <IconChevronRight size={13} stroke={2} />}
          </span>
          <span style={{ width: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>
            {expanded ? <IconFolderOpen size={15} stroke={1.8} color={colors.textMuted} /> : <IconFolder size={15} stroke={1.8} color={colors.textMuted} />}
          </span>
          <span style={{ color: colors.textMuted }}>{entry.name}</span>
        </div>
        {expanded && data?.entries?.map(child => (
          <TreeNode
            key={child.path}
            entry={child}
            activePath={activePath}
            depth={depth + 1}
            onSelectFile={onSelectFile}
          />
        ))}
      </div>
    );
  }

  return (
    <div
      onClick={() => onSelectFile(entry.path)}
      title={entry.path}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        minHeight: 28,
        padding: `4px 8px 4px ${indent}px`,
        cursor: "pointer",
        background: isActive ? colors.accentBg : "transparent",
        borderLeft: isActive ? `2px solid ${colors.accent}` : "2px solid transparent",
        fontSize: 12,
        ...styles.fontMono,
        color: isActive ? colors.text : colors.textMuted,
        userSelect: "none",
      }}
      onMouseOver={(e) => { if (!isActive) e.currentTarget.style.background = colors.surfaceElevated ?? colors.surface; }}
      onMouseOut={(e) => { if (!isActive) e.currentTarget.style.background = "transparent"; }}
    >
      <span style={{ width: 16, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <FileIcon name={entry.name} />
      </span>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {entry.name}
      </span>
    </div>
  );
}

interface NewFileRowProps {
  onConfirm: (name: string) => void;
  onCancel: () => void;
}

function NewFileRow({ onConfirm, onCancel }: NewFileRowProps) {
  const [name, setName] = useState("new_file.py");

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 8px" }}>
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onConfirm(name.trim());
          if (e.key === "Escape") onCancel();
        }}
        style={{
          flex: 1,
          background: colors.surfaceElevated ?? colors.surface,
          border: `1px solid ${colors.accent}`,
          borderRadius: 3,
          color: colors.text,
          fontSize: 12,
          fontFamily: "var(--font-mono)",
          padding: "2px 5px",
          outline: "none",
        }}
      />
      <button
        onClick={() => onConfirm(name.trim())}
        style={{ background: "none", border: "none", color: colors.accent, cursor: "pointer", fontSize: 13, padding: 0 }}
      >✓</button>
      <button
        onClick={onCancel}
        style={{ background: "none", border: "none", color: colors.textMuted, cursor: "pointer", fontSize: 13, padding: 0 }}
      >✕</button>
    </div>
  );
}

export function FileTree({ activePath, onSelectFile }: FileTreeProps) {
  const [addingFile, setAddingFile] = useState(false);
  const { data, isLoading } = useWorkspaceFiles("");
  const { mutate: writeFile } = useWriteWorkspaceFile();

  const handleCreate = (name: string) => {
    if (!name) return;
    const path = `nodes/${name}`;
    writeFile({ path, content: "" }, {
      onSuccess: () => {
        setAddingFile(false);
        onSelectFile(path);
      },
    });
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        borderRight: `1px solid ${colors.border}`,
        background: colors.surface,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          height: 40,
          padding: "0 10px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          fontSize: 11,
          ...styles.fontSans,
          color: colors.textDim,
          textTransform: "uppercase",
          borderBottom: `1px solid ${colors.border}`,
          flexShrink: 0,
        }}
      >
        <span>Workspace</span>
        <button
          type="button"
          title="New file"
          onClick={() => setAddingFile(true)}
          style={{
            width: 26,
            height: 26,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 6,
            border: `1px solid ${colors.border}`,
            background: "transparent",
            color: colors.textMuted,
            cursor: "pointer",
          }}
        >
          <IconPlus size={14} stroke={2} />
        </button>
      </div>

      {/* Tree */}
      <div style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}>
        {isLoading ? (
          <div style={{ padding: "8px 12px", fontSize: 11, color: colors.textDim }}>Loading…</div>
        ) : !data?.entries?.length ? (
          <div style={{ padding: "14px 12px", fontSize: 12, color: colors.textDim, lineHeight: 1.5 }}>
            No files found in this workspace.
          </div>
        ) : (
          data?.entries?.map(entry => (
            <TreeNode
              key={entry.path}
              entry={entry}
              activePath={activePath}
              depth={0}
              onSelectFile={onSelectFile}
            />
          ))
        )}
      </div>

      {/* Footer: new file */}
      <div style={{ borderTop: `1px solid ${colors.border}`, flexShrink: 0 }}>
        {addingFile ? (
          <NewFileRow onConfirm={handleCreate} onCancel={() => setAddingFile(false)} />
        ) : activePath ? (
          <div
            title={activePath}
            style={{
              padding: "7px 10px",
              color: colors.textDim,
              fontSize: 10,
              ...styles.fontMono,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {activePath}
          </div>
        ) : null}
      </div>
    </div>
  );
}
