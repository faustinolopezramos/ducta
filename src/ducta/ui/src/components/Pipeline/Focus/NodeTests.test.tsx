import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NodeTests } from "./NodeTests";

const runMutate = vi.fn();
const state: { files: string[]; result: any } = { files: [], result: null };
vi.mock("../../../api/queries", () => ({
  useNodeTests: () => ({ data: { files: state.files } }),
  useRunNodeTests: () => ({ mutate: runMutate, isPending: false, data: state.result, error: null }),
  useGenerateSnapshotTest: () => ({ mutate: vi.fn(), isPending: false, data: null, error: null }),
}));
vi.mock("../../ui/PermittedButton", () => ({
  PermittedButton: ({ children, onClick, disabled }: any) => (
    <button type="button" onClick={onClick} disabled={disabled}>{children}</button>
  ),
}));

const renderIt = () =>
  render(
    <MemoryRouter>
      <NodeTests projectId="p" node="silver.clean" env="dev" />
    </MemoryRouter>,
  );

describe("NodeTests", () => {
  beforeEach(() => {
    state.files = [];
    state.result = null;
    runMutate.mockReset();
  });

  it("offers a snapshot test when nothing covers the node", () => {
    renderIt();
    expect(screen.getByText(/No test calls/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run tests" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Snapshot test from data" })).toBeEnabled();
  });

  it("runs the node's tests and links a failure to its line", () => {
    state.files = ["tests/test_silver.py"];
    state.result = {
      ok: false,
      summary: { failed: 1, passed: 1 },
      output: "",
      tests: [
        { name: "test_ok", outcome: "passed", file: "tests/test_silver.py", line: 3, seconds: 0 },
        { name: "test_bad", outcome: "failed", file: "src/silver.py", line: 97, message: "AnalysisException", seconds: 0 },
      ],
    };
    renderIt();
    fireEvent.click(screen.getByRole("button", { name: "Run tests" }));
    expect(runMutate).toHaveBeenCalledWith("silver.clean");
    expect(screen.getByText("1 failed · 1 passed")).toBeInTheDocument();
    const where = screen.getByRole("link", { name: "src/silver.py:97" });
    expect(where.getAttribute("href")).toContain("src/silver.py");
    // failures first
    expect(screen.getAllByRole("listitem").map((li) => li.getAttribute("data-outcome")).filter(Boolean)).toEqual(["failed", "passed"]);
  });
});
