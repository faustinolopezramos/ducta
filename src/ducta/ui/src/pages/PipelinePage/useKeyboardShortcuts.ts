import { useEffect, type Dispatch, type SetStateAction } from "react";
import type { Node } from "../../types";

interface NavMaps {
  children: Map<string, string[]>;
  levels: Map<string, number> | null;
  rows: Map<number, string[]>;
}

/** ⌘K finder, arrow-key DAG walking, F fit, R run node, Esc — deselect. */
export function usePipelineKeyboardShortcuts(params: {
  paletteOpen: boolean;
  setPaletteOpen: Dispatch<SetStateAction<boolean>>;
  isCodeEditorOpen: boolean;
  addNodeOpen: boolean;
  viewMode: string;
  selectedNodeId: string | null;
  setSelectedNodeId: (id: string | null) => void;
  pipelineNodes: Node[];
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
    viewMode,
    selectedNodeId,
    setSelectedNodeId,
    pipelineNodes,
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
      if (paletteOpen || mod || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable=true]")) return;
      if (isCodeEditorOpen || addNodeOpen || viewMode !== "flow") return;

      if (e.key === "Escape") {
        setSelectedNodeId(null);
        return;
      }
      if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        fitCanvas();
        return;
      }
      if (e.key === "r" || e.key === "R") {
        const node = pipelineNodes.find((n) => n.id === selectedNodeId);
        if (node && !isExecuting && !runningNodeId) handleRunNode(node);
        return;
      }
      if (!e.key.startsWith("Arrow")) return;
      e.preventDefault();
      const { children, levels, rows } = navMaps;
      if (!selectedNodeId) {
        const first = rows.get(0)?.[0] ?? pipelineNodes[0]?.id;
        if (first) {
          setSelectedNodeId(first);
          centerOnNode(first);
        }
        return;
      }
      let next: string | undefined;
      if (e.key === "ArrowUp") {
        next = (parentsMap.get(selectedNodeId) ?? [])[0];
      } else if (e.key === "ArrowDown") {
        next = (children.get(selectedNodeId) ?? [])[0];
      } else {
        const lvl = levels?.get(selectedNodeId) ?? 0;
        const row = rows.get(lvl) ?? [];
        const idx = row.indexOf(selectedNodeId);
        next = e.key === "ArrowLeft" ? row[idx - 1] : row[idx + 1];
      }
      if (next) {
        setSelectedNodeId(next);
        centerOnNode(next);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    paletteOpen,
    setPaletteOpen,
    isCodeEditorOpen,
    addNodeOpen,
    viewMode,
    selectedNodeId,
    setSelectedNodeId,
    pipelineNodes,
    navMaps,
    parentsMap,
    isExecuting,
    runningNodeId,
    handleRunNode,
    centerOnNode,
    fitCanvas,
  ]);
}
