import { useState } from "react";
import { styles } from "../../theme/tokens";
import type { LogEntry } from "../../store/logsStore";
import { HighlightedText } from "./HighlightedText";
import { AnsiText } from "./AnsiText";
import {
  fmt,
  formatElapsed,
  extractNodeStatus,
  LEVEL_COLOR,
  LEVEL_SHORT,
  LEVEL_BADGE_BG,
  NODE_STATUS_ICON,
  NODE_STATUS_LABEL,
  EXEC_STATE_COLOR,
  type Section,
} from "./logUtils";

// ── NodeListRow ───────────────────────────────────────────────────────────────

const NODE_LIST_STATE_COLOR: Record<string, string> = {
  running:   "var(--ilog-accent)",
  success:   "var(--ilog-green)",
  failed:    "var(--ilog-red)",
  error:     "var(--ilog-red)",
  pending:   "var(--ilog-text-muted)",
  cancelled: "var(--ilog-amber)",
  skipped:   "var(--ilog-amber)",
};

export function NodeListRow({
  label, count, active, dotColor, onSelect,
}: {
  label: string;
  count: number;
  active: boolean;
  dotColor: string;
  onSelect: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => e.key === "Enter" && onSelect()}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "7px 12px",
        background: active ? "var(--ilog-hover)" : hovered ? "var(--ilog-overlay)" : "transparent",
        cursor: "pointer",
        userSelect: "none",
        outline: "none",
        transition: "all 0.1s",
        flexShrink: 0,
        borderLeft: active ? "2px solid var(--ilog-accent)" : "2px solid transparent",
      }}
    >
      <div style={{
        width: 6, height: 6, borderRadius: "50%", background: dotColor,
        boxShadow: active ? `0 0 6px ${dotColor}80` : "none",
        flexShrink: 0,
        transition: "box-shadow 0.2s",
      }} />
      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: active ? "var(--ilog-text)" : hovered ? "var(--ilog-text)" : "var(--ilog-text-dim)",
        flex: 1,
        minWidth: 0,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
        fontWeight: active ? 600 : 400,
        letterSpacing: "0.01em",
        textTransform: "uppercase",
      }}>
        {label}
      </span>
      {count > 0 && (
        <span style={{
          fontFamily: "var(--font-mono)", fontSize: 11,
          background: active ? "var(--ilog-hover)" : "var(--ilog-overlay)",
          color: active ? "var(--ilog-text)" : "var(--ilog-text-dim)",
          padding: "1px 6px", borderRadius: 4, flexShrink: 0,
          border: "1px solid var(--ilog-border)",
        }}>
          {count > 99 ? "99+" : count}
        </span>
      )}
    </div>
  );
}

// ── NodeStatusRow ─────────────────────────────────────────────────────────────

export function NodeStatusRow({
  entry, active, onToggle, t0,
}: {
  entry: LogEntry;
  active: boolean;
  onToggle: () => void;
  t0?: number;
}) {
  const [hovered, setHovered] = useState(false);
  const status = extractNodeStatus(entry.message);
  const icon = NODE_STATUS_ICON[status] ?? "·";
  const label = NODE_STATUS_LABEL[status] ?? status;
  const isRunning = status === "running";
  const isSuccess = status === "success";
  const isFailed = status === "failed" || status === "error";

  let stateColor = "var(--ilog-text-dim)";
  let bgColor = "transparent";
  let borderColor = "var(--ilog-border)";

  if (isRunning) {
    stateColor = "var(--ilog-accent)";
    bgColor = "var(--ilog-blue-bg)";
    borderColor = "rgba(88, 166, 255, 0.2)";
  } else if (isSuccess) {
    stateColor = "var(--ilog-green)";
    bgColor = "var(--ilog-green-bg)";
    borderColor = "rgba(63, 185, 80, 0.2)";
  } else if (isFailed) {
    stateColor = "var(--ilog-red)";
    bgColor = "var(--ilog-red-bg)";
    borderColor = "rgba(248, 81, 73, 0.2)";
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(e) => e.key === "Enter" && onToggle()}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title={active ? "Clear filter" : `Filter to ${entry.nodeId}`}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "9px 16px",
        marginTop: 4,
        marginBottom: 4,
        background: active ? "var(--ilog-hover)" : hovered ? bgColor || "var(--ilog-hover)" : bgColor,
        borderTop: `1px solid ${borderColor}`,
        borderBottom: `1px solid ${borderColor}`,
        cursor: "pointer",
        transition: "all 0.15s",
      }}
    >
      <span style={{
        fontFamily: "var(--font-mono)",
        color: stateColor,
        fontSize: 11,
        fontWeight: 700,
        flexShrink: 0,
        width: 18,
        textAlign: "center",
      }}>
        {icon}
      </span>

      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: "var(--ilog-text)",
        fontWeight: 600,
        flex: 1,
        textTransform: "uppercase",
        letterSpacing: "0.02em",
      }}>
        {entry.nodeId}
      </span>

      <span style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: stateColor,
        fontWeight: 600,
        padding: "2px 8px",
        borderRadius: 4,
        background: isRunning ? "rgba(88, 166, 255, 0.1)" : "transparent",
      }}>
        {isRunning && <span style={{
          width: 4, height: 4, borderRadius: "50%",
          background: "var(--ilog-accent)",
          animation: "ilog-pulse 1.6s ease-in-out infinite",
        }} />}
        {label}
      </span>

      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: "var(--ilog-text-muted)",
        minWidth: 50,
        textAlign: "right",
      }}>
        {t0 ? formatElapsed(t0, entry.timestamp) : fmt(entry.timestamp)}
      </span>
    </div>
  );
}

// ── LogRow ────────────────────────────────────────────────────────────────────

export function LogRow({ entry, searchQuery, t0 }: { entry: LogEntry; searchQuery: string; t0?: number }) {
  const [hovered, setHovered] = useState(false);
  const isCliLine = entry.render === "cli";
  const levelColor = LEVEL_COLOR[entry.level] ?? "var(--ilog-text-dim)";
  const levelShort = LEVEL_SHORT[entry.level] ?? "???";
  const isError   = entry.level === "ERROR";
  const isWarning = entry.level === "WARNING";
  const isDebug   = entry.level === "DEBUG";
  const isSuccess = entry.level === "SUCCESS";

  const handleCopyLine = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(entry.message);
  };

  let messageColor = "var(--ilog-text)";
  let rowBg = "transparent";
  let rowBgHover = "var(--ilog-hover)";

  const isTracebackLine = isError || /Traceback \(most recent call last\)|Exception:|Error:|Faillure:/i.test(entry.message);

  if (isError || isTracebackLine) {
    messageColor = "var(--ilog-red)";
    rowBg = "color-mix(in srgb, var(--danger) 8%, transparent)";
    rowBgHover = "color-mix(in srgb, var(--danger) 14%, transparent)";
  } else if (isWarning) {
    messageColor = "var(--ilog-amber)";
    rowBgHover = "var(--ilog-amber-bg)";
  } else if (isSuccess) {
    messageColor = "var(--ilog-green)";
  } else if (isDebug) {
    messageColor = "var(--ilog-text-dim)";
  } else if (isCliLine) {
    messageColor = "var(--ilog-text)";
  }

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        gap: isCliLine ? 0 : 8,
        lineHeight: "1.5",
        alignItems: "flex-start",
        padding: isCliLine ? "1px 16px" : "3px 16px",
        background: isCliLine ? "var(--ilog-overlay)" : hovered ? rowBgHover : rowBg,
        borderLeft: isTracebackLine ? "3px solid var(--danger)" : "3px solid transparent",
        transition: "background 0.08s",
        position: "relative",
        borderBottom: hovered ? "1px solid var(--ilog-border)" : "1px solid transparent",
      }}
    >
      {!isCliLine && (
        <>
          <span style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--ilog-text-muted)",
            flexShrink: 0,
            minWidth: 52,
            paddingTop: 1,
            opacity: 0.7,
          }}>
            {t0 ? formatElapsed(t0, entry.timestamp) : fmt(entry.timestamp)}
          </span>
          <span style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: "var(--font-mono)",
            fontSize: 8,
            fontWeight: 700,
            color: levelColor,
            background: LEVEL_BADGE_BG[entry.level] || "transparent",
            padding: "1px 5px",
            borderRadius: 3,
            flexShrink: 0,
            minWidth: 28,
            textAlign: "center",
            letterSpacing: "0.04em",
            marginTop: 1,
            border: isDebug ? "1px solid transparent" : undefined,
          }}>
            {levelShort}
          </span>
        </>
      )}
      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: messageColor,
        wordBreak: "break-word",
        whiteSpace: "pre-wrap",
        flex: 1,
        lineHeight: "1.5",
      }}>
        <HighlightedText text={entry.message} query={searchQuery} renderer={(t) => <AnsiText text={t} />} />
      </span>
      {hovered && (
        <button
          onClick={handleCopyLine}
          style={{
            background: "var(--ilog-hover)",
            border: "1px solid var(--ilog-border)",
            borderRadius: 4,
            color: "var(--ilog-text-dim)",
            cursor: "pointer",
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            padding: "2px 7px",
            position: "absolute",
            right: 8,
            top: 1,
            zIndex: 10,
            transition: "all 0.1s",
            fontWeight: 500,
          }}
        >
          copy
        </button>
      )}
    </div>
  );
}

// ── SectionHeaderRow ──────────────────────────────────────────────────────────

export function SectionHeaderRow({
  section, isCollapsed, onToggle, searchQuery, t0,
}: {
  section: Section;
  isCollapsed: boolean;
  onToggle: () => void;
  searchQuery: string;
  t0?: number;
}) {
  const [hovered, setHovered] = useState(false);
  const header = section.headerEntry!;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(e) => e.key === "Enter" && onToggle()}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "7px 16px",
        marginTop: 6,
        marginBottom: 2,
        background: hovered ? "var(--ilog-hover)" : "var(--ilog-surface)",
        borderTop: "1px solid var(--ilog-border-strong)",
        borderBottom: "1px solid var(--ilog-border)",
        cursor: "pointer",
        transition: "background 0.1s",
        position: "sticky",
        top: 0,
        zIndex: 5,
      }}
    >
      <span style={{
        fontSize: 11,
        color: "var(--ilog-text-dim)",
        transition: "transform 0.15s",
        transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)",
        flexShrink: 0,
        width: 12,
        textAlign: "center",
      }}>
        ▼
      </span>
      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: "var(--ilog-text)",
        fontWeight: 700,
        flex: 1,
        letterSpacing: "0.02em",
      }}>
        <HighlightedText text={header.message} query={searchQuery} renderer={(t) => <AnsiText text={t} />} />
      </span>
      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: "var(--ilog-text-muted)",
        flexShrink: 0,
      }}>
        {t0 ? formatElapsed(t0, header.timestamp) : fmt(header.timestamp)}
      </span>
      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: "var(--ilog-text-muted)",
        background: "var(--ilog-overlay)",
        padding: "1px 6px",
        borderRadius: 4,
        flexShrink: 0,
      }}>
        {section.entries.length}
      </span>
    </div>
  );
}
