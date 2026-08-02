import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MiniMap } from "./MiniMap";

describe("MiniMap", () => {
  it("mounts empty and fills in without changing hook order (React #310 regression)", () => {
    const { rerender, container } = render(
      <MiniMap nodes={[]} containerWidth={0} containerHeight={0} />
    );
    expect(container.querySelector(".minimap")).toBeNull();

    expect(() =>
      rerender(
        <MiniMap
          nodes={[{ id: "a", x: 10, y: 10, type: "source" }]}
          containerWidth={800}
          containerHeight={600}
        />
      )
    ).not.toThrow();
    expect(container.querySelector(".minimap")).not.toBeNull();
  });
});
