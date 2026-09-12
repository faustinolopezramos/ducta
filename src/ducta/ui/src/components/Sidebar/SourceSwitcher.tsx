import { useEffect, useRef, useState } from "react";
import { IconChevronDown, IconFolder, IconCheck } from "@tabler/icons-react";
import { StorageService } from "../../utils/storage";
import { useSourceSelection } from "../../hooks/useWorkspaceSelection";
import { sourceLabel } from "../../utils/sourceLabel";

/**
 * Compact recent-sources switcher for the sidebar footer. Switching a source
 * changes every query key, so we persist the choice and reload — matching how
 * the source is bootstrapped on mount.
 */
export function SourceSwitcher({ compact = false }: { compact?: boolean } = {}) {
  const { selectedSource, updateSource } = useSourceSelection();
  const [open, setOpen] = useState(false);
  const recent = StorageService.getRecentSources();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const current = selectedSource ?? StorageService.getSource();
  if (!current && recent.length === 0) return null;

  const others = recent.filter((s) => s !== current);

  const switchTo = (src: string) => {
    if (src === current) {
      setOpen(false);
      return;
    }
    updateSource(src);
    // Full reload: all React Query caches are keyed by the active source.
    globalThis.location.reload();
  };

  const popoverStyle: React.CSSProperties = compact
    ? {
        position: "absolute",
        bottom: 0,
        left: "calc(100% + 8px)",
        width: 220,
        background: "var(--surface-elevated)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-sm)",
        boxShadow: "var(--shadow-lg)",
        zIndex: 100,
        padding: 4,
        maxHeight: 240,
        overflowY: "auto",
      }
    : {
        position: "absolute",
        bottom: "calc(100% + 4px)",
        left: 0,
        right: 0,
        background: "var(--surface-elevated)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-sm)",
        boxShadow: "var(--shadow-lg)",
        zIndex: 100,
        padding: 4,
        maxHeight: 240,
        overflowY: "auto",
      };

  return (
    <div ref={ref} style={{ position: "relative", marginBottom: 8 }}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Switch source workspace"
        title={current ?? "No source selected"}
        disabled={others.length === 0}
        style={
          compact
            ? {
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: 36,
                height: 36,
                margin: "0 auto",
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text)",
                cursor: others.length === 0 ? "default" : "pointer",
              }
            : {
                display: "flex",
                alignItems: "center",
                gap: 6,
                width: "100%",
                padding: "6px 8px",
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text)",
                cursor: others.length === 0 ? "default" : "pointer",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                minWidth: 0,
              }
        }
      >
        <IconFolder size={compact ? 16 : 13} stroke={1.6} style={{ flexShrink: 0, color: "var(--text-muted)" }} />
        {!compact && (
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, textAlign: "left" }}>
            {current ? sourceLabel(current) : "Select source"}
          </span>
        )}
        {!compact && others.length > 0 && <IconChevronDown size={13} stroke={1.6} style={{ flexShrink: 0 }} />}
      </button>

      {open && others.length > 0 && (
        <div
          role="listbox"
          aria-label="Recent sources"
          style={popoverStyle}
        >
          {current && (
            <div
              role="option"
              aria-selected
              title={current}
              style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 8px", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--primary)", borderRadius: 4 }}
            >
              <IconCheck size={12} stroke={2} style={{ flexShrink: 0 }} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sourceLabel(current)}</span>
            </div>
          )}
          {others.map((src) => (
            <button
              key={src}
              role="option"
              aria-selected={false}
              onClick={() => switchTo(src)}
              title={src}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                width: "100%",
                padding: "6px 8px",
                background: "none",
                border: "none",
                cursor: "pointer",
                color: "var(--text)",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                borderRadius: 4,
                textAlign: "left",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--surface-hover)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
            >
              <span style={{ width: 12, flexShrink: 0 }} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sourceLabel(src)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
