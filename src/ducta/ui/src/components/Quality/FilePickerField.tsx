import React, { useState } from "react";
import { useWorkspaceFiles } from "../../api/queries";
import { colors } from "../../theme/tokens";
import {
  IconFolder,
  IconFile,
  IconArrowUp,
  IconFolderOpen,
  IconX,
} from "@tabler/icons-react";

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  borderRadius: 6,
  border: `1px solid ${colors.border}`,
  background: colors.bg,
  color: colors.text,
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  outline: "none",
};

/**
 * Workspace file input with an inline browser (backed by GET /workspace/files)
 * so users pick real files instead of typing workspace-relative paths blind.
 */
export function FilePickerField({
  value,
  onChange,
  placeholder,
  extensions,
}: {
  value: string;
  onChange: (path: string) => void;
  placeholder?: string;
  /** When set, only files with one of these extensions are selectable. */
  extensions?: string[];
}) {
  const [browsing, setBrowsing] = useState(false);
  const [dir, setDir] = useState("");
  const { data, isLoading } = useWorkspaceFiles(browsing ? dir : "");

  const matchesExt = (name: string) =>
    !extensions || extensions.some((ext) => name.toLowerCase().endsWith(ext));

  const parentDir = dir.includes("/") ? dir.slice(0, dir.lastIndexOf("/")) : "";

  return (
    <div>
      <div style={{ display: "flex", gap: 6 }}>
        <input
          style={inputStyle}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
        />
        <button
          type="button"
          onClick={() => setBrowsing((b) => !b)}
          title={browsing ? "Close browser" : "Browse workspace files"}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            padding: "6px 10px",
            borderRadius: 6,
            border: `1px solid ${browsing ? colors.accent : colors.border}`,
            background: browsing ? `${colors.accent}12` : colors.bg,
            color: browsing ? colors.accent : colors.textMuted,
            cursor: "pointer",
            fontSize: 12,
            flexShrink: 0,
          }}
        >
          {browsing ? <IconX size={14} /> : <IconFolderOpen size={14} />}
          Browse
        </button>
      </div>

      {browsing && (
        <div
          style={{
            marginTop: 6,
            border: `1px solid ${colors.border}`,
            borderRadius: 6,
            background: colors.bg,
            maxHeight: 200,
            overflowY: "auto",
          }}
        >
          <div
            style={{
              position: "sticky",
              top: 0,
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "5px 8px",
              borderBottom: `1px solid ${colors.border}`,
              background: colors.surface,
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: colors.textMuted,
            }}
          >
            {dir && (
              <button
                type="button"
                onClick={() => setDir(parentDir)}
                title="Up one level"
                style={{
                  display: "flex",
                  alignItems: "center",
                  background: "none",
                  border: "none",
                  padding: 0,
                  cursor: "pointer",
                  color: colors.textMuted,
                }}
              >
                <IconArrowUp size={13} />
              </button>
            )}
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              /{dir}
            </span>
          </div>

          {isLoading && (
            <p style={{ margin: 0, padding: "8px 10px", fontSize: 11, color: colors.textMuted }}>
              Loading…
            </p>
          )}
          {!isLoading && (data?.entries ?? []).length === 0 && (
            <p style={{ margin: 0, padding: "8px 10px", fontSize: 11, color: colors.textMuted }}>
              Empty directory.
            </p>
          )}
          {(data?.entries ?? []).map((entry) => {
            const isDir = entry.type === "dir";
            const selectable = isDir || matchesExt(entry.name);
            return (
              <button
                key={entry.path}
                type="button"
                disabled={!selectable}
                onClick={() => {
                  if (isDir) setDir(entry.path);
                  else {
                    onChange(entry.path);
                    setBrowsing(false);
                  }
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  width: "100%",
                  padding: "4px 10px",
                  background: "none",
                  border: "none",
                  cursor: selectable ? "pointer" : "default",
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                  color: selectable ? colors.text : colors.textDim,
                  textAlign: "left",
                }}
              >
                {isDir ? (
                  <IconFolder size={13} color={colors.accent} style={{ flexShrink: 0 }} />
                ) : (
                  <IconFile size={13} style={{ flexShrink: 0 }} />
                )}
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {entry.name}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
