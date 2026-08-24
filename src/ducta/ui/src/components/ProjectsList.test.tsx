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
  useServerProjectPipelines: () => ({ data: { pipelines: {} } }),
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
