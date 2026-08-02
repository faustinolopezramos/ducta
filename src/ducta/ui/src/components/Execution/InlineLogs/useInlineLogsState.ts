import { useEffect, useMemo, useRef, useState } from "react";
import {
  useLogsStore,
  useLogLevelCounts,
  useNodeLogCounts,
  type LogLevel,
  type LogEntry,
} from "../../../store/logsStore";
import { groupIntoSections, type Section } from "../logUtils";

export type FlattenedItem =
  | { type: "header"; section: Section; id: string }
  | { type: "log"; entry: LogEntry; id: string };

/**
 * All log-derivation logic for InlineLogs: source selection (props vs.
 * store), search/level/node filtering, section grouping, and the flattened
 * list Virtuoso renders. Kept separate from layout/size state (which lives
 * in the component) since it's the part shared by both the footer and
 * inline (drawer) variants.
 */
export function useInlineLogsState(propsLogs?: LogEntry[]) {
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(() => new Set());

  const toggleSection = (id: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const storeLogs = useLogsStore((s) => s.currentLogs);
  const currentLogs = useMemo(() => propsLogs ?? storeLogs, [propsLogs, storeLogs]);
  const usingStore = propsLogs == null;
  const storeLevelCounts = useLogLevelCounts();
  const storeNodeCounts = useNodeLogCounts();

  const searchFilter = useLogsStore((s) => s.searchFilter);
  const levelFilter = useLogsStore((s) => s.levelFilter);
  const nodeFilter = useLogsStore((s) => s.nodeFilter);
  const autoScroll = useLogsStore((s) => s.autoScroll);
  const isConnected = useLogsStore((s) => s.isConnected);
  const bumpReconnect = useLogsStore((s) => s.bumpReconnectSignal);
  const wasEverConnected = useRef(false);
  if (isConnected) wasEverConnected.current = true;
  // Reset when logs are cleared (new execution starts)
  useEffect(() => { if (currentLogs.length === 0) wasEverConnected.current = false; }, [currentLogs.length]);
  const setSearch = useLogsStore((s) => s.setSearchFilter);
  const setLevel = useLogsStore((s) => s.setLevelFilter);
  const setNodeFilter = useLogsStore((s) => s.setNodeFilter);
  const setAutoScroll = useLogsStore((s) => s.setAutoScroll);

  const nodeLogCounts = useMemo(() => {
    if (usingStore) return storeNodeCounts;
    const counts: Record<string, number> = {};
    for (const log of currentLogs) {
      if (log.nodeId) counts[log.nodeId] = (counts[log.nodeId] ?? 0) + 1;
    }
    return counts;
  }, [usingStore, storeNodeCounts, currentLogs]);

  const nodeFilteredLogs = useMemo(() => {
    if (nodeFilter === null) return currentLogs;
    return currentLogs.filter((log) => log.nodeId === nodeFilter);
  }, [currentLogs, nodeFilter]);

  const filteredLogs = useMemo(() => {
    if (levelFilter === "ALL" && !searchFilter) return nodeFilteredLogs;
    const needle = searchFilter.toLowerCase();
    return nodeFilteredLogs.filter((log) => {
      if (levelFilter !== "ALL" && log.level !== levelFilter) return false;
      if (needle && !log.message.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [nodeFilteredLogs, searchFilter, levelFilter]);

  const sections = useMemo(() => groupIntoSections(filteredLogs), [filteredLogs]);

  const t0 = useMemo(() => {
    if (currentLogs.length === 0) return Date.now();
    return currentLogs[0]?.timestamp ?? Date.now();
  }, [currentLogs.length, currentLogs[0]?.timestamp]);

  const flattenedItems = useMemo<FlattenedItem[]>(() => {
    const items: FlattenedItem[] = [];
    for (const section of sections) {
      if (section.headerEntry) {
        items.push({ type: "header", section, id: `header-${section.id}` });
      }
      if (!collapsedSections.has(section.id)) {
        for (const entry of section.entries) {
          items.push({ type: "log", entry, id: entry.id });
        }
      }
    }
    return items;
  }, [sections, collapsedSections]);

  const levelCounts = useMemo(() => {
    if (usingStore && nodeFilter === null) {
      return { ...storeLevelCounts, ALL: currentLogs.length } as Partial<
        Record<LogLevel | "ALL", number>
      >;
    }
    const counts: Partial<Record<LogLevel | "ALL", number>> = { ALL: nodeFilteredLogs.length };
    for (const log of nodeFilteredLogs) {
      counts[log.level] = (counts[log.level] ?? 0) + 1;
    }
    return counts;
  }, [usingStore, nodeFilter, storeLevelCounts, currentLogs.length, nodeFilteredLogs]);

  const totalCount = currentLogs.length;
  const anyFilter = searchFilter || levelFilter !== "ALL" || nodeFilter !== null;

  useEffect(() => {
    if (currentLogs.length === 0) setCollapsedSections(new Set());
  }, [currentLogs.length]);

  return {
    currentLogs,
    usingStore,
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
    sections,
    t0,
    flattenedItems,
    levelCounts,
    totalCount,
    anyFilter,
    collapsedSections,
    toggleSection,
  };
}
