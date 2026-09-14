import type { LayoutPoint } from "./dagLayout";

/**
 * Smooth path through an edge's waypoints. A direct hop keeps the soft elbow
 * the canvas has always drawn; a routed edge (one that skips layers) becomes a
 * Catmull-Rom spline through its waypoints, with vertical tangents at both ends
 * so it still leaves and enters a card perpendicular to its edge.
 */
export function edgePath(points: LayoutPoint[]): string {
  if (points.length < 2) return "";

  if (points.length === 2) {
    const [a, b] = points;
    const pull = Math.min(Math.max(Math.abs(b.y - a.y) * 0.5, 24), 80);
    return `M ${a.x} ${a.y} C ${a.x} ${a.y + pull}, ${b.x} ${b.y - pull}, ${b.x} ${b.y}`;
  }

  const last = points.length - 1;
  const tangents = points.map((p, i) => {
    if (i === 0) return { x: 0, y: points[1].y - p.y };
    if (i === last) return { x: 0, y: p.y - points[last - 1].y };
    // A point that starts or ends a vertical run gets a vertical tangent, so
    // the run is drawn perfectly straight instead of bowing out of its channel
    // and back into a card. Curvature stays in the gaps between layers.
    const vertical = points[i - 1].x === p.x || points[i + 1].x === p.x;
    return {
      x: vertical ? 0 : (points[i + 1].x - points[i - 1].x) / 2,
      y: (points[i + 1].y - points[i - 1].y) / 2,
    };
  });

  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < last; i++) {
    const p1 = points[i];
    const p2 = points[i + 1];
    const c1x = p1.x + tangents[i].x / 3;
    const c1y = p1.y + tangents[i].y / 3;
    const c2x = p2.x - tangents[i + 1].x / 3;
    const c2y = p2.y - tangents[i + 1].y / 3;
    d += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2.x} ${p2.y}`;
  }
  return d;
}
