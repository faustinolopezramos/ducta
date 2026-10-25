import { useEffect } from "react";
import { useStore } from "@xyflow/react";
import { create } from "zustand";

/**
 * The pipeline canvas' zoom, for the readout in its toolbar. The toolbar sits
 * outside React Flow's provider, and lifting the zoom into page state would
 * re-render the whole page on every wheel tick; this store re-renders only
 * the readout.
 */
export const useCanvasZoom = create<{ zoom: number; set: (zoom: number) => void }>((set) => ({
  zoom: 1,
  set: (zoom) => set({ zoom }),
}));

/** Mounted under the canvas' provider: copies its zoom into the store. */
export function ZoomReporter() {
  const zoom = useStore((s) => s.transform[2]);
  const set = useCanvasZoom((s) => s.set);
  useEffect(() => set(zoom), [zoom, set]);
  return null;
}
