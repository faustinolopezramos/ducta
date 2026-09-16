import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { HUDToolbar } from "./HUDToolbar";

vi.mock("../../store/builderStore", () => ({
  useBuilderStore: (select: (s: unknown) => unknown) =>
    select({ historyIndex: 0, history: [], undo: () => {}, redo: () => {} }),
}));

const base = {
  lens: "flow" as const,
  onLensChange: () => {},
  orientation: "vertical" as const,
  onOrientationChange: () => {},
  onAddNode: () => {},
  onFind: () => {},
};

describe("HUDToolbar", () => {
  it("offers the three lenses and reports the one picked", () => {
    const onLensChange = vi.fn();
    render(<HUDToolbar {...base} onLensChange={onLensChange} />);

    expect(screen.getByRole("tab", { name: "Flow" })).toHaveAttribute("aria-selected", "true");
    screen.getByRole("tab", { name: "List" }).click();
    expect(onLensChange).toHaveBeenCalledWith("list");
    expect(screen.getByRole("tab", { name: "YAML" })).toBeInTheDocument();
  });

  it("lets the viewer choose which way the layers run", () => {
    const onOrientationChange = vi.fn();
    render(<HUDToolbar {...base} onOrientationChange={onOrientationChange} />);

    const down = screen.getByRole("button", { name: "Layers top to bottom" });
    const across = screen.getByRole("button", { name: "Layers left to right" });
    expect(down).toHaveAttribute("aria-pressed", "true");
    expect(across).toHaveAttribute("aria-pressed", "false");

    across.click();
    expect(onOrientationChange).toHaveBeenCalledWith("horizontal");
  });

  it("reflects a horizontal preference", () => {
    render(<HUDToolbar {...base} orientation="horizontal" />);
    expect(screen.getByRole("button", { name: "Layers left to right" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("only offers the orientation on the canvas", () => {
    render(<HUDToolbar {...base} lens="list" />);
    expect(screen.queryByRole("button", { name: "Layers top to bottom" })).toBeNull();
  });

  it("offers Pipeline/Chain only when there is a chain to draw", () => {
    const { unmount } = render(<HUDToolbar {...base} />);
    expect(screen.queryByRole("button", { name: "Chain" })).toBeNull();
    unmount();

    const onScopeChange = vi.fn();
    render(<HUDToolbar {...base} scope="chain" onScopeChange={onScopeChange} />);
    expect(screen.getByRole("button", { name: "Chain" })).toHaveAttribute("aria-pressed", "true");
    screen.getByRole("button", { name: "Pipeline" }).click();
    expect(onScopeChange).toHaveBeenCalledWith("pipeline");
  });

  it("drops the editing controls in the YAML lens", () => {
    render(<HUDToolbar {...base} lens="yaml" />);
    expect(screen.queryByRole("button", { name: "Add node" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Chain" })).toBeNull();
  });
});
