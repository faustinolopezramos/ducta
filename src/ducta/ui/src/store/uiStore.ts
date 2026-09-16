import { create } from "zustand";
import { persist } from "zustand/middleware";

/** Which way a pipeline's layers run on the canvas. A per-user preference. */
export type PipelineOrientation = "vertical" | "horizontal";

/** The ways to work on a pipeline: the canvas, the contract list, or its YAML. */
export type PipelineLens = "flow" | "list" | "yaml";

interface UIState {
  theme: "light" | "dark";
  sidebarCollapsed: boolean;
  /** Top-to-bottom layers by default; left-to-right for people who read a chain that way. */
  pipelineOrientation: PipelineOrientation;
  /** The lens a pipeline opens in when the URL does not name one. */
  pipelineLens: PipelineLens;
  setTheme: (theme: "light" | "dark") => void;
  toggleTheme: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
  setPipelineOrientation: (orientation: PipelineOrientation) => void;
  setPipelineLens: (lens: PipelineLens) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      theme: "light",
      sidebarCollapsed: false,
      pipelineOrientation: "vertical",
      pipelineLens: "flow",
      setTheme: (theme) => {
        document.documentElement.setAttribute("data-theme", theme);
        set({ theme });
      },
      toggleTheme: () => set((state) => {
        const next = state.theme === "light" ? "dark" : "light";
        document.documentElement.setAttribute("data-theme", next);
        return { theme: next };
      }),
      setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setPipelineOrientation: (pipelineOrientation) => set({ pipelineOrientation }),
      setPipelineLens: (pipelineLens) => set({ pipelineLens }),
    }),
    {
      name: "ducta-ui-state",
    }
  )
);
