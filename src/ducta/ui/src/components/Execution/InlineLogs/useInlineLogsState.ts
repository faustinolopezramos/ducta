import { useEffect, useMemo, useRef, useState } from "react";
import {
  useLogsStore,
  useLogLevelCounts,
  useNodeLogCounts,
  type LogLevel,
  type LogEntry,
} from "../../../store/logsStore";
import { groupIntoSections, type Section } from "../logUtils";
import { collapseRepeats, logMatcher } from "../logFilter";

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
      if (next.has(id)) next.delete(id);
      else next.add(id);
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
  // Both the set and the reset live here: writing a ref during render is not
  // safe under concurrent rendering, and splitting the two halves across a
  // render-phase write and an effect made their ordering depend on it.
  useEffect(() => {
    if (currentLogs.length === 0) {
      wasEverConnected.current = false; // new execution — logs were cleared
    } else if (isConnected) {
      wasEverConnected.current = true;
    }
  }, [currentLogs.length, isConnected]);
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

  const matcher = useMemo(() => logMatcher(searchFilter), [searchFilter]);
  const filteredLogs = useMemo(() => {
    if (levelFilter === "ALL" && !searchFilter) return nodeFilteredLogs;
    return nodeFilteredLogs.filter((log) => {
      if (levelFilter !== "ALL" && log.level !== levelFilter) return false;
      if (searchFilter && !matcher.test(log.message)) return false;
      return true;
    });
  }, [nodeFilteredLogs, searchFilter, levelFilter, matcher]);

  // A line repeated back to back (a retry loop, a poll) is shown once, counted.
  const sections = useMemo(
    () => groupIntoSections(filteredLogs).map((sec) => ({ ...sec, entries: collapseRepeats(sec.entries) })),
    [filteredLogs],
  );

  // Mount time, sampled once, as the origin used when the logs carry no
  // timestamp of their own. Read via a lazy initialiser rather than during
  // render: `Date.now()` in a render body (or a useMemo) is impure, and it
  // also made the origin jump every time the memo recomputed.
  const [mountedAt] = useState(() => Date.now());
  const firstTimestamp = currentLogs[0]?.timestamp;
  const t0 = firstTimestamp ?? mountedAt;

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

  // Clearing the logs means a new run: drop the collapse state that belonged
  // to the old one. Adjusted during render so the new run's sections never
  // paint with the previous run's rows collapsed.
  const [hadLogs, setHadLogs] = useState(currentLogs.length > 0);
  const hasLogs = currentLogs.length > 0;
  if (hasLogs !== hadLogs) {
    setHadLogs(hasLogs);
    if (!hasLogs) setCollapsedSections(new Set());
  }

  return {
    searchError: matcher.error,
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
