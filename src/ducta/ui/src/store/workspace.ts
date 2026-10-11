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
  /** Whether an environment was ever chosen (by the user, or the first-visit pick). */
  envPicked: boolean;
  /** 'local' | 'git' — sourced from the resolved source returned by POST /workspace/select */
  sourceType: string | null;
  /** Git URL if sourceType is 'git' */
  gitUrl: string | null;
  setSource: (src: Record<string, unknown>) => void;
  setActiveEnv: (env: string) => void;
  /** First visit only: start in *env* (where the project's runs are) — once. */
  pickInitialEnv: (env: string) => void;
  setSourceType: (type: string) => void;
  setGitUrl: (url: string | null) => void;
  clearSource: () => void;
}

const storeCreator: StateCreator<SourceStore, [["zustand/persist", unknown]]> = (set) => ({
  /** SourceInfo object returned by GET /workspace, or null */
  currentSource: null,

  /** Active environment tab in the config editor */
  activeEnv: "base",

  envPicked: false,

  /** Source type: 'local' or 'git' */
  sourceType: null,

  /** Git URL if sourceType is 'git' */
  gitUrl: null,

  /** Called after fetching source info from the API */
  setSource: (src) => set({ currentSource: src }),

  /** Switch the active environment */
  setActiveEnv: (env) => set({ activeEnv: env, envPicked: true }),

  pickInitialEnv: (env) => set((s) => (s.envPicked ? s : { activeEnv: env, envPicked: true })),

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
    envPicked: state.envPicked,
    sourceType: state.sourceType,
    gitUrl: state.gitUrl,
  }),
  // v0 had no `envPicked`: an environment other than the default was a choice.
  version: 1,
  migrate: (persisted, version) => {
    const state = (persisted ?? {}) as Partial<SourceStore>;
    const picked = version < 1 ? Boolean(state.activeEnv && state.activeEnv !== "base") : Boolean(state.envPicked);
    return {
      currentSource: state.currentSource ?? null,
      activeEnv: state.activeEnv ?? "base",
      envPicked: picked,
      sourceType: state.sourceType ?? null,
      gitUrl: state.gitUrl ?? null,
    };
  },
});

export const useSourceStore = create<SourceStore>()(
  withDevtools(persistedStoreCreator, "SourceStore") as any
);
