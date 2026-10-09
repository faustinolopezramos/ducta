import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CommandMenu } from "./CommandMenu";
import { useCommandMenu } from "./commandStore";

vi.mock("../../api/queries", () => ({
  useServerProjects: () => ({ data: { projects: [{ id: "batch", name: "batch" }] } }),
  useServerProjectPipelines: () => ({ data: { pipelines: { "silver.clean": {} } } }),
  useCodeIndex: () => ({ data: { nodes: [{ node: "silver.clean_student", pipeline: "silver.clean" }], files: { "src/silver.py": [] } } }),
  useProjectDatasets: () => ({ data: { datasets: [{ name: "silver.education.student_cleaned", layer: "silver" }] } }),
  useExecutionList: () => ({ data: { executions: [] } }),
}));

function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>;
}

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<><CommandMenu /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  );

describe("CommandMenu", () => {
  beforeEach(() => useCommandMenu.getState().hide());

  it("is closed until asked for", () => {
    renderAt("/p/batch");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("finds a node by a few letters and goes to it on Enter", () => {
    useCommandMenu.getState().show();
    renderAt("/p/batch");
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "@clstud" } });
    expect(screen.getAllByRole("option")[0]).toHaveTextContent("silver.clean_student");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("where").textContent).toBe("/p/batch/pipelines/silver.clean");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("runs commands", () => {
    useCommandMenu.getState().show(">runs");
    renderAt("/p/batch");
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
    expect(screen.getByTestId("where").textContent).toBe("/p/batch/runs");
  });
});
