import { useStore, type NodeProps } from "@xyflow/react";

export interface BandLabelData {
  layer: string | null;
  pipeline: string;
  current: boolean;
  /** Down the page the label stays on screen when the view is panned past the gutter. */
  sticky?: boolean;
}

/** Screen pixels kept between a stuck label and the canvas' left edge. */
const STICK_AT = 8;

/**
 * A chain band's label ("SILVER silver.clean"), drawn as a React Flow node so
 * it sits above the edges. Inside the band, which is drawn behind everything,
 * the edges crossed it ("golden.trans|formation"). A capsule with its own
 * ground keeps it legible wherever an edge passes.
 */
export function BandLabelNode({ data, positionAbsoluteX }: NodeProps) {
  const d = data as unknown as BandLabelData;
  // Centring a node with the panel open pans the gutter off screen and cut the
  // label to "E bronze.ingestion"; it slides right to stay readable instead.
  const shift = useStore((st) => {
    if (!d.sticky) return 0;
    const [tx, , zoom] = st.transform;
    const screenX = tx + positionAbsoluteX * zoom;
    return screenX < STICK_AT ? (STICK_AT - screenX) / zoom : 0;
  });
  return (
    <span
      style={shift ? { transform: `translateX(${shift}px)` } : undefined}
      className={`strata-band-label${d.current ? " current" : ""}`}
      data-layer={d.layer ?? undefined}
      data-testid="strata-band-label"
    >
      <span className="strata-band-swatch" aria-hidden="true" />
      {d.layer && <span>{d.layer}</span>}
      <span className="strata-band-pipe">{d.pipeline}</span>
    </span>
  );
}
