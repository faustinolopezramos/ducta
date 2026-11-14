import { describe, expect, it } from "vitest";
import { edgePath } from "./edgePath";

describe("edgePath direction", () => {
  it("defaults to top-to-bottom, unchanged", () => {
    expect(
      edgePath([
        { x: 0, y: 0 },
        { x: 100, y: 200 },
      ])
    ).toBe("M 0 0 C 0 80, 100 120, 100 200");
  });

  it("draws a left-to-right hop as the transpose of the top-to-bottom one", () => {
    // Same hop as above with x and y swapped: the elbow now pulls along x.
    expect(
      edgePath(
        [
          { x: 0, y: 0 },
          { x: 200, y: 100 },
        ],
        "LR"
      )
    ).toBe("M 0 0 C 80 0, 120 100, 200 100");
  });

  it("keeps a left-to-right routed edge dead horizontal while it passes a layer", () => {
    const d = edgePath(
      [
        { x: 0, y: 0 },
        { x: 100, y: 50 },
        { x: 200, y: 50 },
        { x: 300, y: 0 },
      ],
      "LR"
    );
    const segments = d.split(" C ").slice(1);
    expect(segments).toHaveLength(3);
    // The middle segment runs between the two channel waypoints: every control
    // point stays on y = 50, so the line cannot bow into a card beside it.
    expect(segments[1]).toMatch(/^[\d.]+ 50, [\d.]+ 50, 200 50$/);
  });
});
