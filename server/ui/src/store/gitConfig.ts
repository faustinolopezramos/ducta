import { create } from "zustand";
import { persist } from "zustand/middleware";

// ─────────────────────────────────────────────
// GIT CONFIG STORE
//
// Tracks whether the user has completed (or
// deliberately skipped) the Git setup wizard.
// Persisted to localStorage so the wizard is
// only shown once per device.
// ─────────────────────────────────────────────

export interface GitConfigStore {
  setupComplete: boolean;
  completedAt: string | null;
  skippedAt: string | null;
  markComplete: () => void;
  markSkipped: () => void;
  reset: () => void;
}

export const useGitConfigStore = create<GitConfigStore>()(
  persist(
    (set) => ({
      /** True once the user clicked "Complete setup" or "Skip". */
      setupComplete: false,

      /** ISO timestamp of the last time the wizard was completed. */
      completedAt: null,

      /** ISO timestamp of the last time the wizard was skipped. */
      skippedAt: null,

      /** Set after the user finishes or skips the wizard. */
      markComplete: () => set({ setupComplete: true, completedAt: new Date().toISOString() }),

      /** Dismiss the wizard without saving — user can re-open from Settings. */
      markSkipped: () => set({ setupComplete: true, skippedAt: new Date().toISOString() }),

      /** Force the wizard to appear again (e.g. from Settings > Git). */
      reset: () => set({ setupComplete: false, completedAt: null, skippedAt: null }),
    }),
    {
      name: "ducta-git-config",
      partialize: (state) => ({
        setupComplete: state.setupComplete,
        completedAt:  state.completedAt,
        skippedAt:    state.skippedAt,
      }),
    }
  )
);
