import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ProjectsList } from "./ProjectsList";
import type { ProjectSummary } from "../types";

// A viewer: may look at projects, may not create or delete them.
vi.mock("../hooks/usePermission", () => ({
  usePermission: (p: string) => p === "project.read",
  usePermissions: () => ({ isLoading: false, can: (p: string) => p === "project.read" }),
  requiresPermission: (p: string) => `Requires the '${p}' permission`,
}));

vi.mock("../api/queries", () => ({
  useCreateServerProject: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteServerProject: () => ({ mutate: vi.fn(), isPending: false }),
  useExecutionList: () => ({ data: { executions: [] }, isLoading: false }),
}));
vi.mock("../api/schedulesApi", () => ({ useSchedules: () => ({ data: { schedules: [], count: 0 } }) }));
vi.mock("../api/templatesApi", () => ({
  useTemplates: () => ({ data: [] }),
  useGenerateFromTemplate: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("../api/mutations", () => ({ apiErrorMessage: (_e: unknown, f: string) => f }));

const projects: ProjectSummary[] = [{ id: "batch", name: "batch", pipelineCount: 6 }];

function renderAsViewer(list: ProjectSummary[] = projects) {
  return render(
    <MemoryRouter>
      <ProjectsList projects={list} />
    </MemoryRouter>
  );
}

describe("The dashboard for a viewer", () => {
  it("still shows every project", () => {
    renderAsViewer();
    expect(screen.getByRole("link", { name: /batch/ })).toBeInTheDocument();
  });

  it("offers no way to create a project", () => {
    renderAsViewer();
    expect(screen.queryByRole("button", { name: /New project/ })).toBeNull();
  });

  it("offers no way to delete one", () => {
    renderAsViewer();
    expect(screen.queryByRole("button", { name: /Delete batch/ })).toBeNull();
  });

  it("does not invite a viewer to create the first project either", () => {
    renderAsViewer([]);
    expect(screen.queryByRole("button", { name: /New project/ })).toBeNull();
  });
});
