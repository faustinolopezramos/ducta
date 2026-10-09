import { create } from "zustand";
import { persist } from "zustand/middleware";

/** Which way a pipeline's layers run on the canvas. A per-user preference. */
export type PipelineOrientation = "vertical" | "horizontal";

/** The ways to work on a pipeline: the canvas, the contract list, or its YAML. */
export type PipelineLens = "flow" | "list" | "yaml";

export type Density = "compact" | "comfortable";

/** What the panel under the canvas shows. */
export type BottomPanelTab = "logs" | "problems" | "preview";

interface UIState {
  theme: "light" | "dark";
  sidebarCollapsed: boolean;
  /** Top-to-bottom layers by default; left-to-right for people who read a chain that way. */
  pipelineOrientation: PipelineOrientation;
  /** The lens a pipeline opens in when the URL does not name one. */
  pipelineLens: PipelineLens;
  /** The project last opened, so workspace-wide pages can lead back to it. */
  lastProjectId: string | null;
  /** IDE shell: panel sizes (px) and visibility, remembered per user. */
  explorerOpen: boolean;
  explorerWidth: number;
  inspectorWidth: number;
  /** Open/closed is the logs store's `logsOpen`: a run opens it. */
  bottomPanelHeight: number;
  bottomPanelTab: BottomPanelTab;
  /** Width the code pane takes beside the canvas. */
  codePaneWidth: number;
  /** Row height: compact for scanning, comfortable for reading. */
  density: Density;
  setTheme: (theme: "light" | "dark") => void;
  toggleTheme: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
  setPipelineOrientation: (orientation: PipelineOrientation) => void;
  setPipelineLens: (lens: PipelineLens) => void;
  setLastProjectId: (id: string | null) => void;
  toggleExplorer: () => void;
  setExplorerWidth: (px: number) => void;
  setInspectorWidth: (px: number) => void;
  setBottomPanelHeight: (px: number) => void;
  setBottomPanelTab: (tab: BottomPanelTab) => void;
  setCodePaneWidth: (px: number) => void;
  setDensity: (density: Density) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      theme: "light",
      sidebarCollapsed: false,
      pipelineOrientation: "vertical",
      pipelineLens: "flow",
      lastProjectId: null,
      explorerOpen: true,
      explorerWidth: 240,
      inspectorWidth: 400,
      bottomPanelHeight: 260,
      bottomPanelTab: "logs",
      codePaneWidth: 560,
      density: "compact",
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
      setLastProjectId: (lastProjectId) => set({ lastProjectId }),
      toggleExplorer: () => set((state) => ({ explorerOpen: !state.explorerOpen })),
      setExplorerWidth: (explorerWidth) => set({ explorerWidth }),
      setInspectorWidth: (inspectorWidth) => set({ inspectorWidth }),
      setBottomPanelHeight: (bottomPanelHeight) => set({ bottomPanelHeight }),
      setBottomPanelTab: (bottomPanelTab) => set({ bottomPanelTab }),
      setCodePaneWidth: (codePaneWidth) => set({ codePaneWidth }),
      setDensity: (density) => set({ density }),
    }),
    {
      name: "ducta-ui-state",
    }
  )
);
