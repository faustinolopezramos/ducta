import { create, type StateCreator } from "zustand";
import { withDevtools } from "./createStore";

export type LogLevel = "DEBUG" | "INFO" | "SUCCESS" | "WARNING" | "ERROR";

export interface LogEntry {
  id: string;
  timestamp: number;
  level: LogLevel;
  message: string;
  nodeId?: string;
  executionId?: string;
  isNodeStatus?: boolean;
  render?: "default" | "cli";
}

type LevelCounts = Record<LogLevel, number>;

const emptyLevelCounts = (): LevelCounts => ({
  DEBUG: 0,
  INFO: 0,
  SUCCESS: 0,
  WARNING: 0,
  ERROR: 0,
});

interface LogsState {
  // Current execution logs
  currentLogs: LogEntry[];
  // Aggregates maintained incrementally (O(Δ) per batch) so consumers don't
  // re-scan the whole currentLogs array on every 100ms log flush.
  levelCounts: LevelCounts;
  nodeLogCounts: Record<string, number>;
  // UI state
  autoScroll: boolean;
  isConnected: boolean;
  searchFilter: string;
  levelFilter: LogLevel | "ALL";
  logsOpen: boolean;
  reconnectSignal: number;
  // Actions
  addLog: (entry: Omit<LogEntry, "id">) => void;
  addLogsBatch: (entries: Omit<LogEntry, "id">[]) => void;
  clearCurrentLogs: () => void;
  setAutoScroll: (enabled: boolean) => void;
  setConnected: (connected: boolean) => void;
  setSearchFilter: (query: string) => void;
  setLevelFilter: (level: LogLevel | "ALL") => void;
  setLogsOpen: (open: boolean) => void;
  bumpReconnectSignal: () => void;
  nodeFilter: string | null;
  setNodeFilter: (nodeId: string | null) => void;
}

const MAX_CURRENT_LOGS = 10000;

const storeCreator: StateCreator<LogsState> = (set, get) => ({
  currentLogs: [],
  levelCounts: emptyLevelCounts(),
  nodeLogCounts: {},
  autoScroll: true,
  isConnected: false,
  searchFilter: "",
  levelFilter: "ALL",
  nodeFilter: null,
  logsOpen: false,
  reconnectSignal: 0,

  addLog: (entry) => {
    get().addLogsBatch([entry]);
  },

  addLogsBatch: (entries) => {
    if (entries.length === 0) return;
    set((state) => {
      const newLogs = entries.map((entry) => ({
        ...entry,
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      }));

      const levelCounts = { ...state.levelCounts };
      const nodeLogCounts = { ...state.nodeLogCounts };

      for (const log of newLogs) {
        levelCounts[log.level] = (levelCounts[log.level] ?? 0) + 1;
        if (log.nodeId) nodeLogCounts[log.nodeId] = (nodeLogCounts[log.nodeId] ?? 0) + 1;
      }

      let updated = [...state.currentLogs, ...newLogs];
      // Keep only last MAX_CURRENT_LOGS entries; decrement aggregates for the
      // evicted prefix so the counts stay consistent with currentLogs.
      if (updated.length > MAX_CURRENT_LOGS) {
        const evicted = updated.slice(0, updated.length - MAX_CURRENT_LOGS);
        updated = updated.slice(-MAX_CURRENT_LOGS);
        for (const log of evicted) {
          levelCounts[log.level] = Math.max(0, (levelCounts[log.level] ?? 0) - 1);
          if (log.nodeId) {
            const next = (nodeLogCounts[log.nodeId] ?? 0) - 1;
            if (next <= 0) delete nodeLogCounts[log.nodeId];
            else nodeLogCounts[log.nodeId] = next;
          }
        }
      }

      return { currentLogs: updated, levelCounts, nodeLogCounts };
    });
  },

  clearCurrentLogs: () => {
    set({
      currentLogs: [],
      levelCounts: emptyLevelCounts(),
      nodeLogCounts: {},
      autoScroll: true,
      nodeFilter: null,
    });
  },

  setAutoScroll: (enabled) => {
    set({ autoScroll: enabled });
  },

  setConnected: (connected) => {
    set({ isConnected: connected });
  },

  setSearchFilter: (query) => {
    set({ searchFilter: query });
  },

  setLevelFilter: (level) => {
    set({ levelFilter: level });
  },

  setLogsOpen: (open) => {
    set({ logsOpen: open });
  },

  bumpReconnectSignal: () => {
    set((s) => ({ reconnectSignal: s.reconnectSignal + 1 }));
  },

  setNodeFilter: (nodeId) => {
    set({ nodeFilter: nodeId });
  },
});

export const useLogsStore = create<LogsState>()(withDevtools(storeCreator, "LogsStore") as any);

// Selector hooks for optimal performance
export const useCurrentLogs = () => useLogsStore((s) => s.currentLogs);
// Note: there's no useFilteredLogs selector — a filtering selector that derives a new
// array every render causes an infinite loop. Filtering lives in useInlineLogsState.ts
// via useMemo with individual state subscriptions instead.
// Incrementally-maintained aggregates over all currentLogs (no per-render scan).
export const useLogLevelCounts = () => useLogsStore((s) => s.levelCounts);
export const useNodeLogCounts = () => useLogsStore((s) => s.nodeLogCounts);
export const useLogsConnected = () => useLogsStore((s) => s.isConnected);
