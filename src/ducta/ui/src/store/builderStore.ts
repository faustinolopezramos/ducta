// ─────────────────────────────────────────────
// BUILDER STORE — Zustand store for the
// Pipeline Builder canvas state.
//
// Manages: nodes, edges, selection, panels,
// undo/redo history, dirty state, validation.
// ─────────────────────────────────────────────

import { create, type StateCreator } from "zustand";
import { immer } from "zustand/middleware/immer";
import { withDevtools } from "./createStore";
import {
  validatePipelineGraph,
  type ValidationResult,
  type BuilderNodeData,
} from "../utils/pipelineValidation";

// ── Types (simplified, not tied to ReactFlow) ────

export interface Node {
  id: string;
  type?: string;
  position?: { x: number; y: number };
  data?: any;
  [key: string]: any;
}

export interface Edge {
  id: string;
  source: string;
  target: string;
  data?: any;
  [key: string]: any;
}

export interface BuilderSnapshot {
  nodes: Node[];
  edges: Edge[];
}

export interface BuilderState {
  // Pipeline metadata
  pipelineName: string;
  pipelineType: string;
  pipelineDescription: string;
  /** Project this pipeline belongs to — required for all server-persist operations. */
  projectId: string;

  // Canvas state
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;

  // Canvas viewport (zoom/pan)
  viewportScale: number;
  viewportX: number;
  viewportY: number;

  // Panel visibility
  paletteOpen: boolean;

  // Undo/redo
  history: BuilderSnapshot[];
  historyIndex: number;

  // Dirty / save tracking
  isDirty: boolean;
  lastSavedAt: number | null;

  // Validation
  validationResults: ValidationResult[];

  // Execution
  executionId: string | null;
  executionStates: Record<string, string>;
  /** Map of node IDs to their active execution IDs for selective node execution */
  activeNodeExecutions: Record<string, string>;

  // Actions
  setPipelineMeta: (meta: { name?: string; type?: string; description?: string; projectId?: string }) => void;
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  addNode: (node: Node) => void;
  removeNode: (id: string) => void;
  updateNodeData: (id: string, data: Partial<BuilderNodeData>) => void;
  addEdge: (edge: Edge) => void;
  removeEdge: (id: string) => void;
  selectNode: (id: string | null) => void;
  togglePalette: () => void;
  pushHistory: () => void;
  undo: () => void;
  redo: () => void;
  validate: () => ValidationResult[];
  markSaved: () => void;
  setExecutionId: (id: string | null) => void;
  setExecutionStates: (states: Record<string, string>) => void;
  addNodeExecution: (nodeId: string, executionId: string) => void;
  removeNodeExecution: (nodeId: string) => void;
  setViewport: (scale: number, x: number, y: number) => void;
  zoomIn: () => void;
  zoomOut: () => void;
  resetViewport: () => void;
  reset: () => void;
}

// Max undo history depth
const MAX_HISTORY = 50;

const initialState = {
  pipelineName: "",
  pipelineType: "batch",
  pipelineDescription: "",
  projectId: "",
  nodes: [] as Node[],
  edges: [] as Edge[],
  selectedNodeId: null as string | null,
  viewportScale: 1,
  viewportX: 0,
  viewportY: 0,
  paletteOpen: true,
  history: [] as BuilderSnapshot[],
  historyIndex: -1,
  isDirty: false,
  lastSavedAt: null as number | null,
  validationResults: [] as ValidationResult[],
  executionId: null as string | null,
  executionStates: {} as Record<string, string>,
  activeNodeExecutions: {} as Record<string, string>,
};

const storeCreator = immer<BuilderState>((set, get) => ({
  ...initialState,

  setPipelineMeta: (meta) =>
    set((s) => {
      s.pipelineName = meta.name ?? s.pipelineName;
      s.pipelineType = meta.type ?? s.pipelineType;
      s.pipelineDescription = meta.description ?? s.pipelineDescription;
      s.projectId = meta.projectId ?? s.projectId;
      s.isDirty = true;
    }),

  setNodes: (nodes) => set({ nodes }),

  setEdges: (edges) => set({ edges }),

  addNode: (node) =>
    set((s) => {
      s.nodes.push(node);
      s.isDirty = true;
    }),

  removeNode: (id) =>
    set((s) => {
      s.nodes = s.nodes.filter((n) => n.id !== id);
      s.edges = s.edges.filter((e) => e.source !== id && e.target !== id);
      if (s.selectedNodeId === id) s.selectedNodeId = null;
      s.isDirty = true;
    }),

  updateNodeData: (id, data) =>
    set((s) => {
      const node = s.nodes.find((n) => n.id === id);
      if (node) {
        node.data = { ...node.data, ...data };
      }
      s.isDirty = true;
    }),

  addEdge: (edge) =>
    set((s) => {
      s.edges.push(edge);
      s.isDirty = true;
    }),

  removeEdge: (id) =>
    set((s) => {
      s.edges = s.edges.filter((e) => e.id !== id);
      s.isDirty = true;
    }),

  selectNode: (id) => set({ selectedNodeId: id }),

  togglePalette: () => set((s) => { s.paletteOpen = !s.paletteOpen; }),

  pushHistory: () =>
    set((s) => {
      const snapshot: BuilderSnapshot = {
        nodes: structuredClone(s.nodes),
        edges: structuredClone(s.edges),
      };
      const truncated = s.history.slice(0, s.historyIndex + 1);
      const newHistory = [...truncated, snapshot].slice(-MAX_HISTORY);
      s.history = newHistory;
      s.historyIndex = newHistory.length - 1;
    }),

  undo: () =>
    set((s) => {
      if (s.historyIndex <= 0) return;
      const newIndex = s.historyIndex - 1;
      const snapshot = s.history[newIndex];
      s.nodes = snapshot.nodes;
      s.edges = snapshot.edges;
      s.historyIndex = newIndex;
      s.isDirty = true;
    }),

  redo: () =>
    set((s) => {
      if (s.historyIndex >= s.history.length - 1) return;
      const newIndex = s.historyIndex + 1;
      const snapshot = s.history[newIndex];
      s.nodes = snapshot.nodes;
      s.edges = snapshot.edges;
      s.historyIndex = newIndex;
      s.isDirty = true;
    }),

  validate: () => {
    const s = get();
    const builderNodes: BuilderNodeData[] = s.nodes
      .filter((n) => n.type === "builder")
      .map((n) => n.data as BuilderNodeData);
    const results = validatePipelineGraph(s.pipelineName, builderNodes);
    set({ validationResults: results });
    return results;
  },

  markSaved: () => set({ isDirty: false, lastSavedAt: Date.now() }),

  setExecutionId: (id) => set({ executionId: id }),
  setExecutionStates: (states) => set({ executionStates: states }),

  /** Add or update a node's active execution ID */
  addNodeExecution: (nodeId: string, executionId: string) =>
    set((s) => {
      s.activeNodeExecutions[nodeId] = executionId;
    }),

  /** Remove a node's active execution (completed) */
  removeNodeExecution: (nodeId: string) =>
    set((s) => {
      delete s.activeNodeExecutions[nodeId];
    }),

  setViewport: (scale, x, y) =>
    set((s) => {
      s.viewportScale = scale;
      s.viewportX = x;
      s.viewportY = y;
    }),

  zoomIn: () =>
    set((s) => {
      const newScale = Math.min(s.viewportScale * 1.25, 3);
      s.viewportScale = newScale;
    }),

  zoomOut: () =>
    set((s) => {
      const newScale = Math.max(s.viewportScale / 1.25, 0.25);
      s.viewportScale = newScale;
    }),

  resetViewport: () =>
    set((s) => {
      s.viewportScale = 1;
      s.viewportX = 0;
      s.viewportY = 0;
    }),

  reset: () => set(initialState),
}));

export const useBuilderStore = create<BuilderState>()(withDevtools(storeCreator, "BuilderStore") as any);
