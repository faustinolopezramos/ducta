import { colors, styles } from "../../theme/tokens";
import { Button } from "../ui";

type SyntaxLevel = 'error' | 'warning' | 'info';

export interface SyntaxIssue {
  level?: SyntaxLevel;
  message: string;
  line?: number | null;
}

interface SyntaxErrorDisplayProps {
  errors: SyntaxIssue[];
  onDismiss?: () => void;
}

const LEVEL_STYLES: Record<SyntaxLevel, { bg: string; border: string; text: string; icon: string }> = {
  error:   { bg: colors.redA12,    border: colors.redA30,    text: colors.red,   icon: "✗" },
  warning: { bg: colors.amberA15,  border: colors.amberA30,  text: colors.warningStrong, icon: "⚠" },
  info:    { bg: colors.blueA12,   border: colors.blueA30,   text: colors.blue,  icon: "ℹ" },
};

export function SyntaxErrorDisplay({ errors, onDismiss }: SyntaxErrorDisplayProps) {
  if (!errors?.length) return null;

  const errorCount   = errors.filter((e) => e.level === "error").length;
  const warningCount = errors.filter((e) => e.level === "warning").length;

  const summaryParts = [];
  if (errorCount)   summaryParts.push(`${errorCount} error${errorCount   !== 1 ? "s" : ""}`);
  if (warningCount) summaryParts.push(`${warningCount} warning${warningCount !== 1 ? "s" : ""}`);
  const infoCount = errors.length - errorCount - warningCount;
  if (infoCount)    summaryParts.push(`${infoCount} hint${infoCount !== 1 ? "s" : ""}`);

  return (
    <div
      style={{
        borderBottom: `1px solid ${colors.border}`,
        background: colors.surface,
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 16px",
          borderBottom: `1px solid ${colors.border}`,
        }}
      >
        <span
          style={{
            ...styles.fontSans,
            fontSize: "var(--text-xs)",
            fontWeight: 600,
            color: errorCount ? colors.red : colors.warningStrong,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
          }}
        >
          {summaryParts.join("  ·  ")}
        </span>
        {onDismiss && (
          <Button variant="ghost" size="sm" onClick={onDismiss} style={{ padding: "2px 8px", transition: "all 0.15s" }}>
            Clear
          </Button>
        )}
      </div>

      {/* Error rows */}
      <div style={{ maxHeight: 180, overflowY: "auto" }}>
        {errors.map((err, i) => {
          const lvl = LEVEL_STYLES[err.level ?? "error"];
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 12,
                padding: "8px 16px",
                borderBottom:
                  i < errors.length - 1 ? `1px solid ${colors.border}` : "none",
                background: lvl.bg,
                transition: "background 0.15s",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = `color-mix(in srgb, ${lvl.bg}, ${colors.surface} 20%)`;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = lvl.bg;
              }}
            >
              <span
                style={{
                  ...styles.fontMono,
                  fontSize: "var(--text-sm)",
                  color: lvl.text,
                  flexShrink: 0,
                  marginTop: 2,
                  fontWeight: 600,
                }}
              >
                {lvl.icon}
              </span>
              {err.line != null && (
                <span
                  style={{
                    ...styles.fontMono,
                    fontSize: "var(--text-2xs)",
                    color: colors.textMuted,
                    flexShrink: 0,
                    paddingTop: 1,
                    minWidth: 42,
                    fontWeight: 600,
                  }}
                >
                  L{err.line}
                </span>
              )}
              <span
                style={{
                  ...styles.fontSans,
                  fontSize: "var(--text-xs)",
                  color: colors.text,
                  wordBreak: "break-word",
                  lineHeight: 1.4,
                }}
              >
                {err.message}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
