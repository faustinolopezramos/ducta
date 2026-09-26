import { useEffect, type Dispatch, type SetStateAction } from "react";
import type { PipelineLens, PipelineOrientation } from "../../store/uiStore";
import { useBuilderStore } from "../../store/builderStore";

interface NavMaps {
  children: Map<string, string[]>;
  levels: Map<string, number> | null;
  rows: Map<number, string[]>;
}

/**
 * ⌘K finder, ⌘Z / ⌘⇧Z undo/redo, arrow-key walking, F fit, O orientation, R run node, Esc deselect.
 *
 * Arrows follow the flow. Along it they step to a dependency or a consumer;
 * across it, to the neighbour in the same layer — so ↑/↓ walk the dependencies
 * when layers run down the page, and ←/→ do when they run across it. In the
 * List lens ↑/↓ move between rows in the order the list shows them.
 */
export function usePipelineKeyboardShortcuts(params: {
  paletteOpen: boolean;
  setPaletteOpen: Dispatch<SetStateAction<boolean>>;
  isCodeEditorOpen: boolean;
  addNodeOpen: boolean;
  lens: PipelineLens;
  orientation: PipelineOrientation;
  onToggleOrientation: () => void;
  selectedNodeId: string | null;
  setSelectedNodeId: (id: string | null) => void;
  /** Every node drawn right now (this pipeline, or its whole chain). */
  pipelineNodes: Array<{ id: string; name?: string }>;
  /** Node ids in the order the List lens shows them. */
  listOrder: string[];
  navMaps: NavMaps;
  parentsMap: Map<string, string[]>;
  isExecuting: boolean;
  runningNodeId: string | null;
  handleRunNode: (node: { id: string; name?: string }) => void;
  centerOnNode: (id: string) => void;
  fitCanvas: () => void;
}) {
  const {
    paletteOpen,
    setPaletteOpen,
    isCodeEditorOpen,
    addNodeOpen,
    lens,
    orientation,
    onToggleOrientation,
    selectedNodeId,
    setSelectedNodeId,
    pipelineNodes,
    listOrder,
    navMaps,
    parentsMap,
    isExecuting,
    runningNodeId,
    handleRunNode,
    centerOnNode,
    fitCanvas,
  } = params;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const isMac = /mac/i.test(navigator.userAgent);
      const mod = isMac ? e.metaKey : e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
        return;
      }
      // Canvas undo/redo (the builder's edit history). Lived in App.tsx, keyed
      // off the URL, next to a second, project-wide undo that is gone now.
      const key = e.key.toLowerCase();
      if (mod && (key === "z" || key === "y")) {
        const target = e.target as HTMLElement | null;
        if (target?.closest("input, textarea, select, [contenteditable=true]")) return;
        e.preventDefault();
        const builder = useBuilderStore.getState();
        if (key === "y" || e.shiftKey) builder.redo();
        else builder.undo();
        return;
      }
      if (paletteOpen || mod || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable=true]")) return;
      if (isCodeEditorOpen || addNodeOpen || lens === "yaml") return;

      const onCanvas = lens === "flow";
      const select = (id: string | undefined) => {
        if (!id) return;
        setSelectedNodeId(id);
        if (onCanvas) centerOnNode(id);
      };

      if (e.key === "Escape") {
        setSelectedNodeId(null);
        return;
      }
      if (onCanvas && (e.key === "f" || e.key === "F")) {
        e.preventDefault();
        fitCanvas();
        return;
      }
      if (onCanvas && (e.key === "o" || e.key === "O")) {
        e.preventDefault();
        onToggleOrientation();
        return;
      }
      if (e.key === "r" || e.key === "R") {
        const node = pipelineNodes.find((n) => n.id === selectedNodeId);
        if (node && !isExecuting && !runningNodeId) handleRunNode(node);
        return;
      }
      if (!e.key.startsWith("Arrow")) return;
      e.preventDefault();

      if (!onCanvas) {
        if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
        const idx = selectedNodeId ? listOrder.indexOf(selectedNodeId) : -1;
        const next = idx < 0 ? listOrder[0] : listOrder[idx + (e.key === "ArrowDown" ? 1 : -1)];
        select(next);
        return;
      }

      const { children, levels, rows } = navMaps;
      if (!selectedNodeId) {
        select(rows.get(0)?.[0] ?? pipelineNodes[0]?.id);
        return;
      }

      const horizontal = orientation === "horizontal";
      const back = horizontal ? "ArrowLeft" : "ArrowUp";
      const forward = horizontal ? "ArrowRight" : "ArrowDown";
      const before = horizontal ? "ArrowUp" : "ArrowLeft";

      if (e.key === back) {
        select((parentsMap.get(selectedNodeId) ?? [])[0]);
      } else if (e.key === forward) {
        select((children.get(selectedNodeId) ?? [])[0]);
      } else {
        const lvl = levels?.get(selectedNodeId) ?? 0;
        const row = rows.get(lvl) ?? [];
        const idx = row.indexOf(selectedNodeId);
        select(e.key === before ? row[idx - 1] : row[idx + 1]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    paletteOpen,
    setPaletteOpen,
    isCodeEditorOpen,
    addNodeOpen,
    lens,
    orientation,
    onToggleOrientation,
    selectedNodeId,
    setSelectedNodeId,
    pipelineNodes,
    listOrder,
    navMaps,
    parentsMap,
    isExecuting,
    runningNodeId,
    handleRunNode,
    centerOnNode,
    fitCanvas,
  ]);
}
