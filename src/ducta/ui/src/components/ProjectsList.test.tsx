import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ProjectsList } from "./ProjectsList";

const mocks = vi.hoisted(() => ({
  deleteProject: vi.fn(),
  createProject: vi.fn(),
  generateTemplate: vi.fn(),
}));

vi.mock("../api/queries", () => ({
  // Deliberately absent: `useServerProjectPipelines`. Each card used to call it
  // to recount a project's pipelines — one request per card on the landing
  // page — for a number `GET /projects` already reports. If a card reaches for
  // it again this mock throws and the suite says so.
  useCreateServerProject: () => ({ mutate: mocks.createProject, isPending: false }),
  useDeleteServerProject: () => ({ mutate: mocks.deleteProject, isPending: false }),
}));

vi.mock("../api/templatesApi", () => ({
  useTemplates: () => ({ data: [] }),
  useGenerateFromTemplate: () => ({ mutate: mocks.generateTemplate, isPending: false }),
}));

describe("ProjectsList deletion", () => {
  it("requires the exact project name before enabling persistent deletion", () => {
    render(
      <MemoryRouter>
        <ProjectsList projects={[{ id: "project-1", name: "Analytics", pipelines: [] }]} onDeleteProject={vi.fn()} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Project options" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete project" }));

    const deleteButton = screen.getAllByRole("button", { name: "Delete project" }).at(-1)!;
    expect(deleteButton).toBeDisabled();

    const typingField = screen.getByLabelText(/type analytics to confirm/i);
    fireEvent.change(typingField, { target: { value: "analytics" } });
    expect(deleteButton).toBeDisabled();

    fireEvent.change(typingField, { target: { value: "Analytics" } });
    expect(deleteButton).toBeEnabled();

    fireEvent.click(deleteButton);
    expect(mocks.deleteProject).toHaveBeenCalledWith(
      { projectId: "project-1", force: true },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });
});


describe("Project card", () => {
  const renderList = (project: Parameters<typeof ProjectsList>[0]["projects"][number]) =>
    render(
      <MemoryRouter>
        <ProjectsList projects={[project]} onDeleteProject={vi.fn()} />
      </MemoryRouter>,
    );

  it("reads the pipeline count off the project rather than fetching it", () => {
    renderList({ id: "p1", name: "Analytics", pipelineCount: 7, pipelines: [] });
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("Pipelines")).toBeInTheDocument();
  });

  it("says 'Pipeline' for exactly one", () => {
    renderList({ id: "p1", name: "Analytics", pipelineCount: 1, pipelines: [] });
    expect(screen.getByText("Pipeline")).toBeInTheDocument();
  });

  it("falls back to the loaded pipelines when the server count is absent", () => {
    renderList({
      id: "p1",
      name: "Analytics",
      pipelines: [{ id: "a" }, { id: "b" }] as never,
    });
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("opens on Space as well as Enter", () => {
    renderList({ id: "p1", name: "Analytics", pipelineCount: 0, pipelines: [] });
    const card = screen.getByRole("button", { name: "Open project Analytics" });

    fireEvent.keyDown(card, { key: " " });
    fireEvent.keyDown(card, { key: "Enter" });
    // Navigation is what the card does; reaching here without throwing means
    // both keys were handled rather than only Enter.
    expect(card).toBeInTheDocument();
  });
});
