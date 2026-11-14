import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { usePipelineKeyboardShortcuts } from "./useKeyboardShortcuts";

type Params = Parameters<typeof usePipelineKeyboardShortcuts>[0];

function Harness(props: Partial<Params>) {
  usePipelineKeyboardShortcuts({
    isCodeEditorOpen: false,
    addNodeOpen: false,
    lens: "flow",
    orientation: "vertical",
    onToggleOrientation: () => {},
    selectedNodeId: null,
    setSelectedNodeId: () => {},
    pipelineNodes: [{ id: "a" }, { id: "b" }],
    listOrder: ["a", "b"],
    navMaps: { children: new Map(), levels: null, rows: new Map([[0, ["a", "b"]]]) },
    parentsMap: new Map(),
    isExecuting: false,
    runningNodeId: null,
    handleRunNode: () => {},
    centerOnNode: () => {},
    fitCanvas: () => {},
    ...props,
  });
  return (
    <>
      <button type="button">Top bar</button>
      <div className="dag-canvas-root">
        <div role="button" tabIndex={0}>card</div>
      </div>
    </>
  );
}

describe("canvas keyboard shortcuts", () => {
  it("leave Tab and the arrows alone outside the graph", () => {
    const select = vi.fn();
    const { getByText } = render(<Harness setSelectedNodeId={select} />);
    const outside = getByText("Top bar");
    const tab = fireEvent.keyDown(outside, { key: "Tab" });
    const down = fireEvent.keyDown(outside, { key: "ArrowDown" });
    expect(tab).toBe(true); // not prevented: the browser moves focus
    expect(down).toBe(true);
    expect(select).not.toHaveBeenCalled();
  });

  it("walk the nodes with Tab on the graph, and let focus leave after the last one", () => {
    const select = vi.fn();
    const { getByText, rerender } = render(<Harness setSelectedNodeId={select} />);
    const card = getByText("card");
    expect(fireEvent.keyDown(card, { key: "Tab" })).toBe(false);
    expect(select).toHaveBeenCalledWith("a");

    rerender(<Harness setSelectedNodeId={select} selectedNodeId="b" />);
    select.mockClear();
    expect(fireEvent.keyDown(getByText("card"), { key: "Tab" })).toBe(true);
    expect(select).not.toHaveBeenCalled();
  });

  it("do not run a node from R typed outside the graph", () => {
    const run = vi.fn();
    const { getByText } = render(<Harness selectedNodeId="a" handleRunNode={run} />);
    fireEvent.keyDown(getByText("Top bar"), { key: "r" });
    expect(run).not.toHaveBeenCalled();
  });
});
