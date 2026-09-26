import { create, type StateCreator } from "zustand";
import { persist } from "zustand/middleware";
import { withDevtools } from "./createStore";

// ─────────────────────────────────────────────
// SOURCE STORE — Zustand with localStorage persistence
// Stores the last known source info returned by the API.
// ─────────────────────────────────────────────

export interface SourceStore {
  currentSource: Record<string, unknown> | null;
  activeEnv: string;
  /** 'local' | 'git' — sourced from the resolved source returned by POST /workspace/select */
  sourceType: string | null;
  /** Git URL if sourceType is 'git' */
  gitUrl: string | null;
  setSource: (src: Record<string, unknown>) => void;
  setActiveEnv: (env: string) => void;
  setSourceType: (type: string) => void;
  setGitUrl: (url: string | null) => void;
  clearSource: () => void;
}

const storeCreator: StateCreator<SourceStore, [["zustand/persist", unknown]]> = (set) => ({
  /** SourceInfo object returned by GET /workspace, or null */
  currentSource: null,

  /** Active environment tab in the config editor */
  activeEnv: "base",

  /** Source type: 'local' or 'git' */
  sourceType: null,

  /** Git URL if sourceType is 'git' */
  gitUrl: null,

  /** Called after fetching source info from the API */
  setSource: (src) => set({ currentSource: src }),

  /** Switch the active environment */
  setActiveEnv: (env) => set({ activeEnv: env }),

  /** Store the resolved source type from POST /workspace/select */
  setSourceType: (type) => set({ sourceType: type }),

  /** Store the Git URL when sourceType is 'git' */
  setGitUrl: (url) => set({ gitUrl: url }),

  /** Called on source init or explicit disconnect */
  clearSource: () =>
    set({ currentSource: null, sourceType: null, gitUrl: null }),
});

const persistedStoreCreator = persist(storeCreator, {
  name: "ducta-source",
  partialize: (state) => ({
    currentSource: state.currentSource,
    activeEnv: state.activeEnv,
    sourceType: state.sourceType,
    gitUrl: state.gitUrl,
  }),
});

export const useSourceStore = create<SourceStore>()(
  withDevtools(persistedStoreCreator, "SourceStore") as any
);
