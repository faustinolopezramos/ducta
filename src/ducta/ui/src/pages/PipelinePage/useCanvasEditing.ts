import { useCallback, useEffect, useRef, useState } from "react";
import { usePipelineOps, type PipelineOp } from "../../api/mutations/pipelineOps";
import { apiErrorMessage } from "../../api/mutations";
import { problemsFromError } from "../../api/queries/problems";
import { toastStore } from "../../hooks/useModalStack";
import { useProblemsStore } from "../../store/problemsStore";
import type { DagCanvasItem } from "../../components/Pipeline/types";
import { datasetsToConnect, wouldCycle } from "./canvasEdits";

const outputsOf = (items: Map<string, DagCanvasItem>, id: string) => (items.get(id)?.outputs ?? []).map((o) => o.name);
const inputsOf = (items: Map<string, DagCanvasItem>, id: string) => (items.get(id)?.inputs ?? []).map((i) => i.name);

/** One step in the canvas history: what it was, and how to take it back. */
interface Step {
  pipeline: string;
  label: string;
  /** The ops that undo it (or, on the redo stack, redo it). */
  ops: PipelineOp[];
}

/**
 * Editing the graph from the canvas. Every change is a small operation on the
 * pipeline's file (comments kept), validated by the server, not committed; the
 * server answers with the operations that undo it, so ⌘Z and the toast's
 * "Undo" replay those rather than guessing.
 */
export function useCanvasEditing({
  projectId,
  pipelineId,
  version,
  itemById,
  parentsMap,
}: {
  projectId: string | undefined;
  pipelineId: string | undefined;
  /** The pipelines' current version (OCC). */
  version: string | undefined;
  itemById: Map<string, DagCanvasItem>;
  parentsMap: Map<string, string[]>;
}) {
  const { mutateAsync } = usePipelineOps();
  const setProblems = useProblemsStore((s) => s.setProblems);
  const [undoStack, setUndo] = useState<Step[]>([]);
  const [redoStack, setRedo] = useState<Step[]>([]);
  const [busy, setBusy] = useState(false);
  // The version the next edit is made against: the latest the server gave us,
  // so two quick edits do not race the refetch.
  const versionRef = useRef(version);
  useEffect(() => {
    versionRef.current = version;
  }, [version]);

  // A different pipeline is a different history (reset during render, not in an effect).
  const [historyFor, setHistoryFor] = useState(pipelineId);
  if (historyFor !== pipelineId) {
    setHistoryFor(pipelineId);
    setUndo([]);
    setRedo([]);
  }

  const run = useCallback(
    async (pipeline: string, ops: PipelineOp[], newDatasets?: Record<string, Record<string, unknown>>) => {
      if (!projectId) throw new Error("No project");
      setBusy(true);
      try {
        const result = await mutateAsync({ projectId, pipeline, ops, expectedVersion: versionRef.current, newDatasets });
        versionRef.current = result.version;
        setProblems(projectId, "save", []);
        return result;
      } catch (err) {
        setProblems(projectId, "save", problemsFromError(err));
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [projectId, mutateAsync, setProblems],
  );

  const undo = useCallback(async () => {
    const step = undoStack[undoStack.length - 1];
    if (!step || busy) return;
    try {
      const result = await run(step.pipeline, step.ops);
      setUndo((s) => s.slice(0, -1));
      setRedo((s) => [...s, { ...step, ops: result.inverse }]);
      toastStore.getState().show(`Undid: ${step.label}`, "info", 3000);
    } catch (err) {
      toastStore.getState().show(apiErrorMessage(err, "Could not undo"), "error");
    }
  }, [undoStack, busy, run]);

  const redo = useCallback(async () => {
    const step = redoStack[redoStack.length - 1];
    if (!step || busy) return;
    try {
      const result = await run(step.pipeline, step.ops);
      setRedo((s) => s.slice(0, -1));
      setUndo((s) => [...s, { ...step, ops: result.inverse }]);
    } catch (err) {
      toastStore.getState().show(apiErrorMessage(err, "Could not redo"), "error");
    }
  }, [redoStack, busy, run]);

  /** Apply an edit to this pipeline, record it, and offer to undo it. */
  const apply = useCallback(
    async (label: string, ops: PipelineOp[], newDatasets?: Record<string, Record<string, unknown>>) => {
      if (!pipelineId) return false;
      try {
        const result = await run(pipelineId, ops, newDatasets);
        const step = { pipeline: pipelineId, label, ops: result.inverse };
        setUndo((s) => [...s.slice(-49), step]);
        setRedo([]);
        toastStore.getState().show(label, "success", 6000, {
          label: "Undo",
          onClick: () => {
            // The toast's Undo replays this step even if others followed it.
            run(step.pipeline, step.ops)
              .then(() => setUndo((s) => s.filter((x) => x !== step)))
              .catch((err) => toastStore.getState().show(apiErrorMessage(err, "Could not undo"), "error"));
          },
        });
        return true;
      } catch (err) {
        toastStore.getState().show(apiErrorMessage(err, `Could not ${label.toLowerCase()}`), "error");
        return false;
      }
    },
    [pipelineId, run],
  );

  /** May `to` read what `from` writes? Same pipeline target, no loop, something new to read. */
  const canConnect = useCallback(
    (from: string, to: string) => {
      const target = itemById.get(to);
      if (!target || (target.pipeline && target.pipeline !== pipelineId)) return false;
      if (wouldCycle(from, to, parentsMap)) return false;
      return datasetsToConnect(outputsOf(itemById, from), inputsOf(itemById, to)).length > 0;
    },
    [itemById, parentsMap, pipelineId],
  );

  /** Drag from → to: `to` reads every dataset `from` writes that it did not read yet. */
  const connect = useCallback(
    (from: string, to: string) => {
      const datasets = datasetsToConnect(outputsOf(itemById, from), inputsOf(itemById, to));
      if (datasets.length === 0) {
        toastStore.getState().show(`${from} writes nothing ${to} does not already read`, "info");
        return;
      }
      void apply(
        `Connect ${datasets.join(", ")} → ${to}`,
        datasets.map((dataset) => ({ op: "connect" as const, node: to, dataset })),
      );
    },
    [apply, itemById],
  );

  const disconnect = useCallback(
    (node: string, dataset: string) => apply(`Disconnect ${dataset} from ${node}`, [{ op: "disconnect", node, dataset }]),
    [apply],
  );

  const removeNode = useCallback((node: string) => apply(`Remove ${node}`, [{ op: "remove_node", node }]), [apply]);

  return {
    apply,
    connect,
    canConnect,
    disconnect,
    removeNode,
    undo,
    redo,
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
    busy,
  };
}
