import { useState } from "react";
import { IconChevronDown, IconChevronRight } from "@tabler/icons-react";
import { StatusBadge } from "../ui/StatusBadge";
import type { LogEntry } from "../../store/logsStore";
import { HighlightedText } from "./HighlightedText";
import { AnsiText } from "./AnsiText";
import {
  fmt,
  formatElapsed,
  extractNodeStatus,
  LEVEL_COLOR,
  LOG_TIME_COL_WIDTH,
  type Section,
} from "./logUtils";

// ── NodeListRow ───────────────────────────────────────────────────────────────

export function NodeListRow({
  label, count, active, status, onSelect,
}: {
  label: string;
  count: number;
  active: boolean;
  status: string;
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
        background: active ? "var(--surface-hover)" : hovered ? "var(--overlay-subtle)" : "transparent",
        cursor: "pointer",
        userSelect: "none",
        outline: "none",
        transition: "all 0.1s",
        flexShrink: 0,
        borderLeft: active ? "2px solid var(--primary)" : "2px solid transparent",
      }}
    >
      <StatusBadge status={status} variant="dot" size="sm" />
      <span style={{
        fontFamily: "var(--font-sans)",
        fontSize: "var(--text-xs)",
        color: active ? "var(--text)" : hovered ? "var(--text)" : "var(--text-dim)",
        flex: 1,
        minWidth: 0,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
        fontWeight: active ? 600 : 400,
      }}>
        {label}
      </span>
      {count > 0 && (
        <span style={{
          fontFamily: "var(--font-sans)", fontSize: "var(--text-xs)",
          background: active ? "var(--surface-hover)" : "var(--overlay-subtle)",
          color: active ? "var(--text)" : "var(--text-dim)",
          padding: "1px 6px", borderRadius: "var(--radius-sm)", flexShrink: 0,
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
  const isRunning = status === "running";
  const isSuccess = status === "success";
  const isFailed = status === "failed" || status === "error";

  // Sourced from the shared --status-* tokens (not hardcoded rgba literals)
  // so this band actually adapts to light mode instead of always rendering
  // the dark-theme tint regardless of the active theme.
  let bgColor = "transparent";
  let borderColor = "var(--border)";
  if (isRunning) {
    bgColor = "var(--status-running-bg)";
    borderColor = "var(--status-running-border)";
  } else if (isSuccess) {
    bgColor = "var(--status-success-bg)";
    borderColor = "var(--status-success-border)";
  } else if (isFailed) {
    bgColor = "var(--status-failed-bg)";
    borderColor = "var(--status-failed-border)";
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
        padding: "var(--space-2) var(--space-4)",
        marginTop: 4,
        marginBottom: 4,
        background: active ? "var(--surface-hover)" : hovered ? bgColor || "var(--surface-hover)" : bgColor,
        borderTop: `1px solid ${borderColor}`,
        borderBottom: `1px solid ${borderColor}`,
        cursor: "pointer",
        transition: "all 0.15s",
      }}
    >
      <StatusBadge status={status} size="sm" />

      <span style={{
        fontFamily: "var(--font-sans)",
        fontSize: "var(--text-sm)",
        color: "var(--text)",
        fontWeight: "var(--weight-medium)",
        flex: 1,
      }}>
        {entry.nodeId}
      </span>

      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-xs)",
        color: "var(--text-muted)",
        minWidth: LOG_TIME_COL_WIDTH,
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
  const levelColor = LEVEL_COLOR[entry.level] ?? "var(--text-dim)";
  const isError   = entry.level === "ERROR";
  const isWarning = entry.level === "WARNING";
  const isDebug   = entry.level === "DEBUG";
  const isSuccess = entry.level === "SUCCESS";

  const handleCopyLine = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(entry.message);
  };

  // Color carries signal, not decoration: an error/warning line gets a left
  // rail plus colored text, and a background tint only on hover (the same
  // interactive affordance every other row gets) — never a persistent
  // full-row wash, which would compete with the rail for attention.
  let messageColor = "var(--text)";
  let rowBgHover = "var(--surface-hover)";
  let railColor = "transparent";

  const isTracebackLine = isError || /Traceback \(most recent call last\)|Exception:|Error:|Faillure:/i.test(entry.message);

  if (isError || isTracebackLine) {
    messageColor = "var(--status-failed-fg)";
    rowBgHover = "var(--status-failed-bg)";
    railColor = "var(--status-failed-fg)";
  } else if (isWarning) {
    messageColor = "var(--status-warning-fg)";
    rowBgHover = "var(--status-warning-bg)";
    railColor = "var(--status-warning-fg)";
  } else if (isSuccess) {
    messageColor = "var(--status-success-fg)";
  } else if (isDebug) {
    messageColor = "var(--text-dim)";
  } else if (isCliLine) {
    messageColor = "var(--text)";
  }

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        gap: isCliLine ? 0 : 8,
        lineHeight: "var(--leading-relaxed)",
        alignItems: "flex-start",
        padding: isCliLine ? "1px var(--space-4)" : "var(--space-2) var(--space-4)",
        background: isCliLine ? "var(--overlay-subtle)" : hovered ? rowBgHover : "transparent",
        borderLeft: `3px solid ${railColor}`,
        transition: "background 0.08s",
        position: "relative",
        borderBottom: hovered ? "1px solid var(--border)" : "1px solid transparent",
      }}
    >
      {!isCliLine && (
        <>
          <span style={{
            fontFamily: "var(--font-mono)",
            fontSize: "var(--text-xs)",
            color: "var(--text-muted)",
            flexShrink: 0,
            minWidth: LOG_TIME_COL_WIDTH,
            textAlign: "right",
            paddingTop: 3,
            opacity: 0.7,
          }}>
            {t0 ? formatElapsed(t0, entry.timestamp) : fmt(entry.timestamp)}
          </span>
          <span
            title={entry.level}
            className="ilog__level-dot"
            style={{ background: levelColor, marginTop: 7 }}
          />
        </>
      )}
      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-sm)",
        color: messageColor,
        wordBreak: "break-word",
        whiteSpace: "pre-wrap",
        flex: 1,
        lineHeight: "var(--leading-relaxed)",
      }}>
        <HighlightedText text={entry.message} query={searchQuery} renderer={(t) => <AnsiText text={t} />} />
      </span>
      {hovered && (
        <button
          onClick={handleCopyLine}
          style={{
            background: "var(--surface-hover)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            color: "var(--text-dim)",
            cursor: "pointer",
            fontSize: "var(--text-xs)",
            fontFamily: "var(--font-sans)",
            padding: "2px 7px",
            position: "absolute",
            right: 8,
            top: 1,
            zIndex: 10,
            transition: "all 0.1s",
            fontWeight: "var(--weight-medium)",
          }}
        >
          Copy
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
  const Chevron = isCollapsed ? IconChevronRight : IconChevronDown;

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
        padding: "var(--space-2) var(--space-4)",
        marginTop: 6,
        marginBottom: 2,
        background: hovered ? "var(--surface-hover)" : "var(--surface)",
        borderTop: "1px solid var(--border)",
        borderBottom: "1px solid var(--border)",
        cursor: "pointer",
        transition: "background 0.1s",
        position: "sticky",
        top: 0,
        zIndex: 5,
      }}
    >
      <Chevron size={14} stroke={1.75} color="var(--text-dim)" style={{ flexShrink: 0 }} />
      <span style={{
        fontFamily: "var(--font-sans)",
        fontSize: "var(--text-sm)",
        color: "var(--text)",
        fontWeight: "var(--weight-semibold)",
        flex: 1,
      }}>
        <HighlightedText text={header.message} query={searchQuery} renderer={(t) => <AnsiText text={t} />} />
      </span>
      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-xs)",
        color: "var(--text-muted)",
        flexShrink: 0,
        minWidth: LOG_TIME_COL_WIDTH,
        textAlign: "right",
      }}>
        {t0 ? formatElapsed(t0, header.timestamp) : fmt(header.timestamp)}
      </span>
      <span style={{
        fontFamily: "var(--font-sans)",
        fontSize: "var(--text-xs)",
        color: "var(--text-muted)",
        background: "var(--overlay-subtle)",
        padding: "1px 6px",
        borderRadius: "var(--radius-sm)",
        flexShrink: 0,
      }}>
        {section.entries.length}
      </span>
    </div>
  );
}
