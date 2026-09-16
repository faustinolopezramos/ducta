import type { LayoutDirection, LayoutPoint } from "./dagLayout";

/**
 * Smooth path through an edge's waypoints. A direct hop keeps the soft elbow
 * the canvas has always drawn; a routed edge (one that skips layers) becomes a
 * Catmull-Rom spline through its waypoints, with tangents along the flow at
 * both ends so it still leaves and enters a card perpendicular to its edge.
 *
 * The curve is computed in a frame where the flow runs down the y axis — which
 * is what `TB` already is — and a left-to-right (`LR`) layout is simply that
 * frame transposed, so each emitted coordinate is swapped back on the way out.
 */
export function edgePath(points: LayoutPoint[], direction: LayoutDirection = "TB"): string {
  if (points.length < 2) return "";

  const lr = direction === "LR";
  const pts = lr ? points.map((p) => ({ x: p.y, y: p.x })) : points;
  const xy = (x: number, y: number) => (lr ? `${y} ${x}` : `${x} ${y}`);

  if (pts.length === 2) {
    const [a, b] = pts;
    const pull = Math.min(Math.max(Math.abs(b.y - a.y) * 0.5, 24), 80);
    return `M ${xy(a.x, a.y)} C ${xy(a.x, a.y + pull)}, ${xy(b.x, b.y - pull)}, ${xy(b.x, b.y)}`;
  }

  const last = pts.length - 1;
  const tangents = pts.map((p, i) => {
    if (i === 0) return { x: 0, y: pts[1].y - p.y };
    if (i === last) return { x: 0, y: p.y - pts[last - 1].y };
    // A point that starts or ends a straight run along the flow gets a tangent
    // along the flow, so the run is drawn perfectly straight instead of bowing
    // out of its channel and back into a card. Curvature stays in the gaps
    // between layers.
    const straight = pts[i - 1].x === p.x || pts[i + 1].x === p.x;
    return {
      x: straight ? 0 : (pts[i + 1].x - pts[i - 1].x) / 2,
      y: (pts[i + 1].y - pts[i - 1].y) / 2,
    };
  });

  let d = `M ${xy(pts[0].x, pts[0].y)}`;
  for (let i = 0; i < last; i++) {
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const c1x = p1.x + tangents[i].x / 3;
    const c1y = p1.y + tangents[i].y / 3;
    const c2x = p2.x - tangents[i + 1].x / 3;
    const c2y = p2.y - tangents[i + 1].y / 3;
    d += ` C ${xy(c1x, c1y)}, ${xy(c2x, c2y)}, ${xy(p2.x, p2.y)}`;
  }
  return d;
}
