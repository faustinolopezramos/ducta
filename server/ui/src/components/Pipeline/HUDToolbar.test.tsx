import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { HUDToolbar } from "./HUDToolbar";
import { useCanvasZoom } from "./canvasZoom";

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
};

const openView = () => fireEvent.click(screen.getByRole("button", { name: /^View/ }));

describe("HUDToolbar", () => {
  it("offers the three lenses and reports the one picked", () => {
    const onLensChange = vi.fn();
    render(<HUDToolbar {...base} onLensChange={onLensChange} />);
    expect(screen.getByRole("tab", { name: "Flow" })).toHaveAttribute("aria-selected", "true");
    screen.getByRole("tab", { name: "List" }).click();
    expect(onLensChange).toHaveBeenCalledWith("list");
    expect(screen.getByRole("tab", { name: "YAML" })).toBeInTheDocument();
  });

  it("chooses which way the layers run from the View menu, which says what is on", () => {
    const onOrientationChange = vi.fn();
    render(<HUDToolbar {...base} onOrientationChange={onOrientationChange} />);
    expect(screen.getByRole("button", { name: /^View/ })).toHaveAccessibleName("View: ↓");
    openView();
    expect(screen.getByRole("radio", { name: "Top to bottom" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: /Left to right/ }));
    expect(onOrientationChange).toHaveBeenCalledWith("horizontal");
  });

  it("offers Pipeline or chain only when there is a chain to draw", () => {
    const { unmount } = render(<HUDToolbar {...base} />);
    openView();
    expect(screen.queryByRole("radio", { name: "With the upstream chain" })).toBeNull();
    unmount();

    const onScopeChange = vi.fn();
    render(<HUDToolbar {...base} scope="chain" onScopeChange={onScopeChange} />);
    expect(screen.getByRole("button", { name: /^View/ })).toHaveAccessibleName("View: with chain, ↓");
    openView();
    expect(screen.getByRole("radio", { name: "With the upstream chain" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "Only this pipeline" }));
    expect(onScopeChange).toHaveBeenCalledWith("pipeline");
  });

  it("collapses the namespaces from the View menu", () => {
    const onCollapseAll = vi.fn();
    render(<HUDToolbar {...base} groups={{ count: 3, collapsed: 0, onCollapseAll, onExpandAll: () => {} }} />);
    openView();
    fireEvent.click(screen.getByRole("checkbox", { name: "Collapse each namespace (3)" }));
    expect(onCollapseAll).toHaveBeenCalled();
  });

  it("names the pipeline a new node goes into", () => {
    render(<HUDToolbar {...base} addNodeTarget="golden.transformation" />);
    expect(screen.getByRole("button", { name: "Add node to golden.transformation" })).toBeInTheDocument();
  });

  it("drops the editing controls and the direction in the YAML lens", () => {
    render(<HUDToolbar {...base} lens="yaml" onScopeChange={() => {}} />);
    expect(screen.queryByRole("button", { name: "Add node" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^View/ })).toBeNull();
  });

  it("shows the zoom and resets it to 100%", () => {
    useCanvasZoom.getState().set(0.76);
    const onResetZoom = vi.fn();
    render(
      <HUDToolbar {...base} onZoomIn={() => {}} onZoomOut={() => {}} onFitView={() => {}} onResetZoom={onResetZoom} />
    );
    const readout = screen.getByRole("button", { name: "Zoom 76%, reset to 100%" });
    fireEvent.click(readout);
    expect(onResetZoom).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Full screen canvas" })).toBeInTheDocument();
  });
});
