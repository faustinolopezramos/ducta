import { useRef, useState, useCallback } from "react";
import {
  IconAlertTriangle,
  IconCopy,
  IconDownload,
  IconSearch,
  IconX,
  IconChevronUp,
  IconArrowDown,
  IconMinus,
  IconArrowsMaximize,
  IconArrowsMinimize,
  IconTerminal2,
} from "@tabler/icons-react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { colors } from "../../../theme/tokens";
import { type LogLevel, type LogEntry } from "../../../store/logsStore";
import { NodeListRow, NodeStatusRow, LogRow, SectionHeaderRow } from "../LogRows";
import { EXEC_STATE_COLOR, LEVELS } from "../logUtils";
import { NodeChip, StatusLabel, ResizeHandle } from "./subcomponents";
import { useInlineLogsState, type FlattenedItem } from "./useInlineLogsState";
import "../InlineLogs.css";

type LogSize = "normal" | "expanded" | "fullscreen";

export function InlineLogs({
  isRunning,
  onClose,
  variant = "inline",
  nodes,
  executionStates = {},
  logs: propsLogs,
}: {
  isRunning: boolean;
  onClose?: () => void;
  variant?: "inline" | "footer";
  nodes?: Array<{ id: string; name: string }>;
  executionStates?: Record<string, string>;
  logs?: LogEntry[];
}) {
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const [size, setSize] = useState<LogSize>("normal");
  const [minimized, setMinimized] = useState(false);
  const [customHeight, setCustomHeight] = useState<number | null>(null);

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
    levelCounts,
    totalCount,
    anyFilter,
    collapsedSections,
    toggleSection,
  } = useInlineLogsState(propsLogs);

  const hasNodePanel = nodes != null && nodes.length > 0;

  const handleClose = () => {
    setNodeFilter(null);
    onClose?.();
  };

  const cycleSize = () => {
    setSize((prev) => {
      if (prev === "normal") return "expanded";
      if (prev === "expanded") return "fullscreen";
      return "normal";
    });
  };

  const handleResize = useCallback((delta: number) => {
    setCustomHeight((prev) => Math.max(150, (prev ?? 380) + delta));
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
      <LogRow entry={item.entry} searchQuery={searchFilter} t0={t0} />
    );
  }, [collapsedSections, searchFilter, nodeFilter, setNodeFilter, t0, toggleSection]);

  const isFullscreen = size === "fullscreen";
  const isExpanded = size === "expanded";
  const bodyMaxHeight = isFullscreen
    ? "calc(100vh - 120px)"
    : isExpanded
    ? customHeight != null ? `${customHeight}px` : "60vh"
    : undefined;

  const bodyClass = [
    "ilog__body",
    `ilog__body--${variant}`,
    isExpanded && "ilog__body--expanded",
    isFullscreen && "ilog__body--fullscreen",
  ]
    .filter(Boolean)
    .join(" ");

  const rootClass = [
    "ilog",
    variant === "inline" && "ilog--inline",
    isFullscreen && "ilog--fullscreen",
  ]
    .filter(Boolean)
    .join(" ");

  if (minimized) {
    const errorCount = levelCounts.ERROR ?? 0;
    const warnCount = levelCounts.WARNING ?? 0;
    return (
      <div className={`ilog ilog--minimized${variant === "inline" ? " ilog--inline" : ""}`}>
        <button
          className="ilog__minibar"
          onClick={() => setMinimized(false)}
          aria-expanded={false}
          aria-label="Expand logs panel"
        >
          <IconTerminal2 size={14} color={colors.accent} stroke={2} />
          <StatusLabel isRunning={isRunning} />
          <span className="ilog__entry-count">{totalCount} entries</span>
          {errorCount > 0 && <span className="ilog__mini-badge ilog__mini-badge--error">{errorCount} err</span>}
          {warnCount > 0 && <span className="ilog__mini-badge ilog__mini-badge--warn">{warnCount} warn</span>}
          <span className="ilog__minibar-spacer" />
          <IconChevronUp size={16} />
        </button>
      </div>
    );
  }

  return (
    <>
      {isFullscreen && (
        // Click-outside to leave fullscreen; the header keeps an explicit
        // control for it, so the backdrop is scenery.
        <div
          className="ilog__backdrop"
          role="presentation"
          onClick={() => setSize("expanded")}
        />
      )}
      <div className={rootClass}>
        {/* Resize handle — only in expanded or footer mode, not in fullscreen */}
        {!isFullscreen && (
          <ResizeHandle onResize={handleResize} />
        )}

        {/* Header */}
        <div className="ilog__header">
          <div className="ilog__header-left">
            <IconTerminal2 size={16} color={colors.accent} stroke={2} />
            <StatusLabel isRunning={isRunning} />

            {/* Node chips */}
            {nodes && nodes.length > 0 && (
              <div className="ilog__chips-group">
                {nodes.map((node) => (
                  <NodeChip
                    key={node.id}
                    name={node.name || node.id}
                    state={executionStates[node.id] ?? "idle"}
                  />
                ))}
              </div>
            )}

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
              <IconCopy size={15} stroke={1.5} />
            </button>
            <button
              onClick={handleDownload}
              title="Download logs"
              aria-label="Download logs"
              className="ilog__btn"
            >
              <IconDownload size={15} stroke={1.5} />
            </button>

            <div className="ilog__divider" style={{ margin: "0 4px" }} />

            <button
              onClick={() => setMinimized(true)}
              title="Minimize"
              aria-label="Minimize logs panel"
              className="ilog__btn"
            >
              <IconMinus size={18} />
            </button>

            <button
              onClick={cycleSize}
              title={isFullscreen ? "Exit fullscreen (Esc)" : size === "expanded" ? "Fullscreen" : "Expand"}
              aria-label={isFullscreen ? "Exit fullscreen" : size === "expanded" ? "Enter fullscreen" : "Expand logs"}
              className="ilog__btn"
            >
              {isFullscreen ? (
                <IconArrowsMinimize size={16} />
              ) : size === "expanded" ? (
                <IconArrowsMaximize size={16} />
              ) : (
                <IconChevronUp size={18} />
              )}
            </button>

            {onClose && (
              <button
                onClick={handleClose}
                className="ilog__btn ilog__btn--close"
                title="Close"
                aria-label="Close logs panel"
              >
                <IconX size={18} />
              </button>
            )}
          </div>
        </div>

        {/* Body */}
        <div className={bodyClass} style={bodyMaxHeight ? { maxHeight: bodyMaxHeight } : undefined}>
          {/* Node panel */}
          {hasNodePanel && (
            <div className="ilog__sidebar">
              <NodeListRow
                label="ALL NODES"
                count={totalCount}
                active={nodeFilter === null}
                dotColor={isRunning ? colors.accent : colors.textDim}
                onSelect={() => setNodeFilter(null)}
              />
              <div className="ilog__sidebar-divider" />
              {nodes!.map((node) => {
                const state = executionStates[node.id];
                const dotColor = EXEC_STATE_COLOR[state ?? ""] ?? colors.textDim;
                return (
                  <NodeListRow
                    key={node.id}
                    label={node.name || node.id}
                    count={nodeLogCounts[node.id] ?? 0}
                    active={nodeFilter === node.id}
                    dotColor={dotColor}
                    onSelect={() => setNodeFilter(nodeFilter === node.id ? null : node.id)}
                  />
                );
              })}
            </div>
          )}

          {/* Main content */}
          <div className="ilog__content">
            {/* Toolbar */}
            <div className="ilog__toolbar">
              <div className="ilog__level-pills">
                {LEVELS.map((lvl) => {
                  const active = levelFilter === lvl;
                  const col = lvl === "ALL" ? colors.text : (EXEC_STATE_COLOR[lvl] ?? colors.textDim);
                  const count = levelCounts[lvl as LogLevel | "ALL"];
                  const hasEntries = count != null && count > 0;

                  return (
                    <button
                      key={lvl}
                      onClick={() => setLevel(lvl)}
                      className={`ilog__level-pill${active ? " ilog__level-pill--active" : ""}${
                        !hasEntries && lvl !== "ALL" ? " ilog__level-pill--disabled" : ""
                      }`}
                    >
                      {lvl}
                      {count != null && count > 0 && lvl !== "ALL" && (
                        <span className="ilog__level-badge">{count > 99 ? "99+" : count}</span>
                      )}
                    </button>
                  );
                })}
              </div>

              <div className="ilog__search-box">
                <IconSearch size={12} className="ilog__search-icon" />
                <input
                  type="text"
                  value={searchFilter}
                  onChange={(e) => setSearch(e.target.value)}
                  onKeyDown={(e) => e.key === "Escape" && setSearch("")}
                  placeholder="Search logs..."
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
            </div>

            {/* Log list */}
            <div className="ilog__list-container">
              {flattenedItems.length === 0 ? (
                <div className="ilog__list-empty">
                  {isRunning ? (
                    <>
                      <IconTerminal2 size={24} stroke={1} className="ilog__list-empty-icon" style={{ opacity: 0.2 }} />
                      <span className="ilog__list-empty-text">
                        Waiting for output...
                      </span>
                      <span className="ilog__list-empty-hint">
                        Logs will appear here as nodes execute
                      </span>
                    </>
                  ) : (
                    <>
                      <IconTerminal2 size={24} stroke={1} className="ilog__list-empty-icon" style={{ opacity: 0.2 }} />
                      <span className="ilog__list-empty-text">
                        {anyFilter ? "No matches found" : "No logs"}
                      </span>
                      <span className="ilog__list-empty-hint">
                        {anyFilter ? "Try adjusting your search or filters" : "Run a pipeline to see execution logs"}
                      </span>
                    </>
                  )}
                </div>
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
                    <IconArrowDown size={12} stroke={3} />
                    LATEST
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Connection lost banner */}
      {!isConnected && isRunning && wasEverConnected.current && (
        <div className="ilog__footer-error">
          <IconAlertTriangle size={14} />
          CONNECTION LOST — logs may be stale
          <button
            onClick={bumpReconnect}
            className="ilog__reconnect-btn"
          >
            RECONNECT
          </button>
        </div>
      )}
      </div>
    </>
  );
}
