import { colors, styles } from "../../theme/tokens";
import { Button } from "../ui";

interface CodeToolbarProps {
  onFormat: () => void;
  onLint: () => void;
  onSave: () => void;
  saving: boolean;
  dirty: boolean;
  lastSaved: Date | null;
  nodeName: string;
  modulePath?: string;
}

function formatTime(date: Date | null): string | null {
  if (!date) return null;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function CodeToolbar({
  onFormat,
  onLint,
  onSave,
  saving,
  dirty,
  lastSaved,
  nodeName,
  modulePath,
}: CodeToolbarProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 16px",
        background: colors.surface,
        borderBottom: `1px solid ${colors.border}`,
        gap: 12,
        flexShrink: 0,
      }}
    >
      {/* Left: module path and status */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {modulePath && (
          <span
            style={{
              ...styles.fontMono,
              fontSize: 12,
              color: colors.text,
              fontWeight: 500,
            }}
          >
            {modulePath}
          </span>
        )}
        {nodeName && !modulePath && (
          <span style={{ ...styles.fontMono, fontSize: 12, color: colors.text, fontWeight: 500 }}>
            {nodeName}
          </span>
        )}
        <span
          style={{
            ...styles.fontMono,
            fontSize: 10,
            padding: "3px 8px",
            background: `color-mix(in srgb, ${colors.blue} 10%, transparent)`,
            border: `1px solid ${colors.blue}20`,
            color: colors.blue,
            borderRadius: 5,
            fontWeight: 600,
            letterSpacing: "0.02em",
          }}
        >
          Python
        </span>

        {/* Dirty / saved status */}
        {dirty ? (
          <span
            style={{
              ...styles.fontSans,
              fontSize: 11,
              color: colors.warningStrong,
              display: "flex",
              alignItems: "center",
              gap: 5,
              fontWeight: 500,
            }}
          >
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: colors.amber, display: "inline-block" }} />
            Unsaved
          </span>
        ) : lastSaved ? (
          <span style={{ ...styles.fontSans, fontSize: 11, color: colors.green, fontWeight: 500 }}>
            ✓ Saved {formatTime(lastSaved)}
          </span>
        ) : null}
      </div>

      {/* Right: action buttons */}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button
          variant="ghost"
          size="sm"
          onClick={onFormat}
          title="Format: normalize indentation and trim whitespace"
          style={{ transition: "all 0.15s" }}
        >
          ⌁ Format
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onLint}
          title="Run basic static checks on the code"
          style={{ transition: "all 0.15s" }}
        >
          ✓ Lint
        </Button>
        <Button variant="ghost"
          size="sm"
          onClick={onSave}
          loading={saving}
          disabled={!dirty && !saving}
          title="Save (Ctrl+S)"
          style={{ minWidth: 80, transition: "all 0.15s" }}
        >
          {saving ? "Saving…" : dirty ? "Save *" : "Saved"}
        </Button>
      </div>
    </div>
  );
}
