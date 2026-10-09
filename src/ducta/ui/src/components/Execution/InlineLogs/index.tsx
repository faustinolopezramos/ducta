import { useEffect, useRef, useState, useCallback } from "react";
import { createPortal } from "react-dom";
import {
  IconAlertTriangle,
  IconCopy,
  IconDownload,
  IconSearch,
  IconX,
  IconArrowDown,
  IconArrowsMaximize,
  IconArrowsMinimize,
  IconTerminal2,
} from "@tabler/icons-react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { StatusBadge } from "../../ui/StatusBadge";
import { EmptyState } from "../../ui/EmptyState";
import { Toolbar } from "../../ui/Toolbar";
import { type LogLevel, type LogEntry } from "../../../store/logsStore";
import { NodeListRow, NodeStatusRow, LogRow, SectionHeaderRow } from "../LogRows";
import { LEVEL_COLOR, LEVEL_LABEL, LEVELS } from "../logUtils";
import { ResizeHandle } from "./subcomponents";
import { useInlineLogsState, type FlattenedItem } from "./useInlineLogsState";
import "../InlineLogs.css";

const DOCKED_MIN_HEIGHT = 160;
const DOCKED_MAX_HEIGHT = 760;
const DOCKED_DEFAULT_HEIGHT = 340;

/**
 * How the panel is hosted, each with one sizing contract:
 *  - "docked": floats over the pipeline canvas. Owns its own height (resizable
 *    by drag, toggled to fullscreen); the host only positions it.
 *  - "fill": stretches to fill whatever space the host already allocated
 *    (a drawer, a modal body). No resize handle — the host owns the box.
 *  - "bounded": sits inline in a page's flow with a capped height and its own
 *    internal scroll, never taller than its content warrants.
 */
export type LogPanelMode = "docked" | "fill" | "bounded";

export function InlineLogs({
  isRunning,
  onClose,
  mode = "bounded",
  nodes,
  executionStates = {},
  logs: propsLogs,
  lineLink,
  highlightId,
  finalStatus,
}: {
  /** How the run ended, once it has — the header says so instead of "Idle". */
  finalStatus?: string;
  /** A URL to one line (the run page's `?log=`), for each row's link button. */
  lineLink?: (entry: LogEntry) => string | undefined;
  /** Scroll to and mark this line. */
  highlightId?: string;
  isRunning: boolean;
  onClose?: () => void;
  mode?: LogPanelMode;
  nodes?: Array<{ id: string; name: string }>;
  executionStates?: Record<string, string>;
  logs?: LogEntry[];
}) {
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const errorCursor = useRef(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const itemsRef = useRef<FlattenedItem[]>([]);

  const [isFullscreen, setIsFullscreen] = useState(false);
  const [dockedHeight, setDockedHeight] = useState(DOCKED_DEFAULT_HEIGHT);

  const {
    searchFilter,
    levelFilter,
    nodeFilter,
    autoScroll,
    isConnected,
    wasEverConnected,
    setSearch,
    setLevel,
    setNodeFilter,
    setAutoScroll,
    bumpReconnect,
    nodeLogCounts,
    filteredLogs,
    t0,
    flattenedItems,
    searchError,
    levelCounts,
    totalCount,
    anyFilter,
    collapsedSections,
    toggleSection,
  } = useInlineLogsState(propsLogs);
  useEffect(() => {
    itemsRef.current = flattenedItems;
  }, [flattenedItems]);
  // A link to a line: scroll there once its row exists.
  const scrolledTo = useRef<string | null>(null);
  useEffect(() => {
    if (!highlightId || scrolledTo.current === highlightId) return;
    const index = flattenedItems.findIndex((it) => it.type === "log" && it.entry.id === highlightId);
    if (index < 0) return;
    setAutoScroll(false);
    // The list may not be mounted on the first pass: try until it is.
    const timer = setInterval(() => {
      if (!virtuosoRef.current) return;
      virtuosoRef.current.scrollToIndex({ index, align: "center" });
      scrolledTo.current = highlightId;
      clearInterval(timer);
    }, 100);
    return () => clearInterval(timer);
  }, [highlightId, flattenedItems, setAutoScroll]);
  // F8 / ⇧F8 while focus is in the panel: next / previous error, as in an
  // editor's problem list. A native listener: the panel is not a widget.
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "F8") return;
      e.preventDefault();
      const errors = itemsRef.current
        .map((item, i) => (item.type === "log" && item.entry.level === "ERROR" ? i : -1))
        .filter((i) => i >= 0);
      if (errors.length === 0) return;
      const next = e.shiftKey
        ? [...errors].reverse().find((i) => i < errorCursor.current) ?? errors[errors.length - 1]
        : errors.find((i) => i > errorCursor.current) ?? errors[0];
      errorCursor.current = next;
      setAutoScroll(false);
      virtuosoRef.current?.scrollToIndex({ index: next, align: "center", behavior: "smooth" });
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [setAutoScroll]);

  const hasNodePanel = nodes != null && nodes.length > 0;

  const handleResize = useCallback((delta: number) => {
    setDockedHeight((prev) => Math.min(DOCKED_MAX_HEIGHT, Math.max(DOCKED_MIN_HEIGHT, prev + delta)));
  }, []);

  const handleCopy = () => {
    const text = filteredLogs.map(l => `[${new Date(l.timestamp).toISOString()}] ${l.level}: ${l.message}`).join("\n");
    navigator.clipboard.writeText(text);
  };

  const handleDownload = () => {
    const text = filteredLogs.map(l => `[${new Date(l.timestamp).toISOString()}] ${l.level}: ${l.message}`).join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ducta-logs-${new Date().toISOString()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const renderItem = useCallback((_index: number, item: FlattenedItem) => {
    if (item.type === "header") {
      return (
        <SectionHeaderRow
          section={item.section}
          isCollapsed={collapsedSections.has(item.section.id)}
          onToggle={() => toggleSection(item.section.id)}
          searchQuery={searchFilter}
          t0={t0}
        />
      );
    }

    return item.entry.isNodeStatus ? (
      <NodeStatusRow
        entry={item.entry}
        active={nodeFilter === item.entry.nodeId}
        onToggle={() => setNodeFilter(nodeFilter === item.entry.nodeId ? null : item.entry.nodeId ?? null)}
        t0={t0}
      />
    ) : (
      <LogRow
        entry={item.entry}
        searchQuery={searchFilter}
        t0={t0}
        lineLink={lineLink?.(item.entry)}
        highlighted={highlightId === item.entry.id}
      />
    );
  }, [collapsedSections, searchFilter, nodeFilter, setNodeFilter, t0, toggleSection, lineLink, highlightId]);

  const rootClass = [
    "ilog",
    `ilog--${mode}`,
    isFullscreen && "ilog--fullscreen",
  ]
    .filter(Boolean)
    .join(" ");

  // Fullscreen is an overlay sized by inset:0; a docked panel's own drag-to-
  // resize height must not fight that, so it's only applied while docked.
  const rootStyle = mode === "docked" && !isFullscreen ? { height: dockedHeight } : undefined;

  const emptyState = flattenedItems.length === 0 ? (
    isRunning ? (
      <EmptyState
        icon={IconTerminal2}
        size="sm"
        title="Waiting for output"
        description="Logs will appear here as nodes execute."
      />
    ) : (
      <EmptyState
        icon={IconTerminal2}
        size="sm"
        title={anyFilter ? "No matches found" : "No logs"}
        description={anyFilter ? "Try adjusting your search or filters." : "Run a pipeline to see execution logs."}
      />
    )
  ) : null;

  const panel = (
    <>
      {isFullscreen && (
        // Click-outside returns to the panel's normal size; the header keeps
        // an explicit control for it too, so the backdrop is scenery.
        //
        // Rendered through the same portal as the panel below (see the
        // return statement at the bottom): `.page-transition`, which wraps
        // every page, plays a mount animation on `transform`, and per spec
        // that gives it a containing block for any `position: fixed`
        // descendant for as long as the animation (or its `forwards` fill)
        // leaves any transform applied — including the identity matrix it
        // ends on. Left un-ported, "fullscreen" would be clipped to the
        // page's box instead of covering the viewport.
        <div
          className="ilog__backdrop"
          role="presentation"
          onClick={() => setIsFullscreen(false)}
        />
      )}
      <div className={rootClass} style={rootStyle} ref={rootRef}>
        {mode === "docked" && !isFullscreen && (
          <ResizeHandle onResize={handleResize} />
        )}

        {/* Header */}
        <div className="ilog__header">
          <div className="ilog__header-left">
            <IconTerminal2 size={16} color="var(--text-muted)" stroke={1.75} />
            <StatusBadge
              status={isRunning ? "running" : (finalStatus ?? "idle")}
              label={isRunning ? "Live" : finalStatus ? undefined : "Idle"}
              size="sm"
            />

            <div className="ilog__divider" />
            <span className="ilog__entry-count">
              {anyFilter ? `${filteredLogs.length} / ${totalCount}` : `${totalCount} entries`}
            </span>
          </div>

          <div className="ilog__header-right">
            <button
              onClick={handleCopy}
              title="Copy logs"
              aria-label="Copy logs"
              className="ilog__btn"
            >
              <IconCopy size={15} stroke={1.75} />
            </button>
            <button
              onClick={handleDownload}
              title="Download logs"
              aria-label="Download logs"
              className="ilog__btn"
            >
              <IconDownload size={15} stroke={1.75} />
            </button>

            <div className="ilog__divider" style={{ margin: "0 4px" }} />

            <button
              onClick={() => setIsFullscreen((prev) => !prev)}
              title={isFullscreen ? "Exit fullscreen (Esc)" : "Fullscreen"}
              aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
              className="ilog__btn"
            >
              {isFullscreen ? <IconArrowsMinimize size={16} stroke={1.75} /> : <IconArrowsMaximize size={16} stroke={1.75} />}
            </button>

            {onClose && (
              <button
                onClick={onClose}
                className="ilog__btn ilog__btn--close"
                title="Close"
                aria-label="Close logs panel"
              >
                <IconX size={18} stroke={1.75} />
              </button>
            )}
          </div>
        </div>

        {/* Body */}
        <div className="ilog__body">
          {/* Node panel */}
          {hasNodePanel && (
            <div className="ilog__sidebar">
              <NodeListRow
                label="All nodes"
                count={totalCount}
                active={nodeFilter === null}
                status={isRunning ? "running" : "idle"}
                onSelect={() => setNodeFilter(null)}
              />
              <div className="ilog__sidebar-divider" />
              {nodes!.map((node) => (
                <NodeListRow
                  key={node.id}
                  label={node.name || node.id}
                  count={nodeLogCounts[node.id] ?? 0}
                  active={nodeFilter === node.id}
                  status={executionStates[node.id] ?? "idle"}
                  onSelect={() => setNodeFilter(nodeFilter === node.id ? null : node.id)}
                />
              ))}
            </div>
          )}

          {/* Main content */}
          <div className="ilog__content">
            {/* Toolbar */}
            <Toolbar
              className="ilog__toolbar"
              aria-label="Log filters"
              end={
                <div className="ilog__search-box">
                  <IconSearch size={12} className="ilog__search-icon" />
                  <input
                    type="text"
                    value={searchFilter}
                    onChange={(e) => setSearch(e.target.value)}
                    onKeyDown={(e) => e.key === "Escape" && setSearch("")}
                    placeholder="Search logs…  /regex/"
                    aria-invalid={!!searchError}
                    title={searchError ? `Not a valid pattern: ${searchError}` : "Text, or /a regular expression/"}
                    className="ilog__search-input"
                  />
                  {searchFilter && (
                    <button
                      onClick={() => setSearch("")}
                      className="ilog__search-clear"
                    >
                      <IconX size={12} />
                    </button>
                  )}
                </div>
              }
            >
              <div className="ilog__level-pills">
                {LEVELS.map((lvl) => {
                  const active = levelFilter === lvl;
                  const col = lvl === "ALL" ? "var(--text)" : (LEVEL_COLOR[lvl as LogLevel] ?? "var(--text-dim)");
                  const count = levelCounts[lvl as LogLevel | "ALL"];
                  const hasEntries = count != null && count > 0;

                  return (
                    <button
                      key={lvl}
                      onClick={() => setLevel(lvl)}
                      className={`ilog__level-pill${active ? " ilog__level-pill--active" : ""}${
                        !hasEntries && lvl !== "ALL" ? " ilog__level-pill--disabled" : ""
                      }`}
                      style={{ color: col }}
                    >
                      {LEVEL_LABEL[lvl]}
                      {count != null && count > 0 && lvl !== "ALL" && (
                        <span className="ilog__level-badge">{count > 99 ? "99+" : count}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            </Toolbar>

            {/* Log list */}
            <div className="ilog__list-container">
              {emptyState ? (
                <div className="ilog__list-empty">{emptyState}</div>
              ) : (
                <Virtuoso
                  ref={virtuosoRef}
                  data={flattenedItems}
                  itemContent={renderItem}
                  followOutput={autoScroll ? "smooth" : false}
                  atBottomStateChange={(atBottom) => setAutoScroll(atBottom)}
                  style={{ height: "100%" }}
                  totalCount={flattenedItems.length}
                  initialTopMostItemIndex={flattenedItems.length - 1}
                />
              )}

              {/* Scroll to latest button */}
              {!autoScroll && flattenedItems.length > 0 && (
                <div className="ilog__scroll-to-latest">
                  <button
                    onClick={() => {
                      setAutoScroll(true);
                      virtuosoRef.current?.scrollToIndex({ index: flattenedItems.length - 1, behavior: "smooth" });
                    }}
                    className="ilog__scroll-btn"
                  >
                    <IconArrowDown size={12} stroke={2.5} />
                    Latest
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Connection lost banner */}
        {!isConnected && isRunning && wasEverConnected.current && (
          <div className="ilog__footer-error">
            <IconAlertTriangle size={14} stroke={1.75} />
            Connection lost — logs may be stale
            <button
              onClick={bumpReconnect}
              className="ilog__reconnect-btn"
            >
              Reconnect
            </button>
          </div>
        )}
      </div>
    </>
  );

  return isFullscreen ? createPortal(panel, document.body) : panel;
}
