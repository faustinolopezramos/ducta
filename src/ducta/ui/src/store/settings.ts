import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface SettingsStore {
  editorFontSize: number;
  editorTabSize: number;
  editorLineNumbers: boolean;
  editorWordWrap: boolean;
  sidebarCollapsed: boolean;
  compactMode: boolean;
  defaultDryRun: boolean;
  autoScrollLogs: boolean;
  lastNodeType: string;
  preferredView: 'list' | 'graph';

  set: <K extends keyof Omit<SettingsStore, 'set' | 'reset'>>(key: K, value: Omit<SettingsStore, 'set' | 'reset'>[K]) => void;
  reset: () => void;
}

const defaults = {
  editorFontSize: 13,
  editorTabSize: 4,
  editorLineNumbers: true,
  editorWordWrap: false,
  sidebarCollapsed: false,
  compactMode: false,
  defaultDryRun: false,
  autoScrollLogs: true,
  lastNodeType: 'transform',
  preferredView: 'list' as const,
};

export const useSettingsStore = create<SettingsStore>()(
  persist(
    (set) => ({
      ...defaults,
      set: (key, value) => set({ [key]: value }),
      reset: () => set(defaults),
    }),
    { name: "ducta-settings" }
  )
);
