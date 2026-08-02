import { create, type StateCreator } from "zustand";
import { devtools, persist } from "zustand/middleware";

// ─────────────────────────────────────────────
// SOURCE STORE — Zustand with localStorage persistence
// Stores the last known source info returned by the API.
// ─────────────────────────────────────────────

export interface SourceStore {
  currentSource: Record<string, unknown> | null;
  activeEnv: string;
  /** 'local' | 'git' — sourced from SourceInfo.source_type returned by POST /connect */
  sourceType: string | null;
  /** Git URL if sourceType is 'git' */
  gitUrl: string | null;
  setSource: (src: Record<string, unknown>) => void;
  setActiveEnv: (env: string) => void;
  setSourceType: (type: string) => void;
  setGitUrl: (url: string | null) => void;
  clearSource: () => void;
}

const isDev = import.meta.env.DEV;

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

  /** Store the resolved source type from POST /connect */
  setSourceType: (type) => set({ sourceType: type }),

  /** Store the Git URL when sourceType is 'git' */
  setGitUrl: (url) => set({ gitUrl: url }),

  /** Called on source init or explicit disconnect */
  clearSource: () =>
    set({ currentSource: null, sourceType: null, gitUrl: null }),
});

export const useSourceStore = create<SourceStore>()(
  (isDev
    ? devtools(
        persist(storeCreator, {
          name: "ducta-source",
          partialize: (state) => ({
            currentSource: state.currentSource,
            activeEnv: state.activeEnv,
            sourceType: state.sourceType,
            gitUrl: state.gitUrl,
          }),
        }),
        { name: "SourceStore" }
      )
    : persist(storeCreator, {
        name: "ducta-source",
        partialize: (state) => ({
          currentSource: state.currentSource,
          activeEnv: state.activeEnv,
          sourceType: state.sourceType,
          gitUrl: state.gitUrl,
        }),
      })
  ) as any
);
