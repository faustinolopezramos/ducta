import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectsList } from "./ProjectsList";
import type { ProjectSummary } from "../types";

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();
const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

const mocks = vi.hoisted(() => ({
  deleteProject: vi.fn(),
  createProject: vi.fn(),
  generateTemplate: vi.fn(),
  runs: [] as unknown[],
  schedules: [] as unknown[],
}));

// The dashboard is tested as someone who may create and delete projects; what a viewer
// sees is covered in ProjectsList.permissions.test.tsx.
vi.mock("../hooks/usePermission", () => ({
  usePermission: () => true,
  usePermissions: () => ({ isLoading: false, can: () => true }),
  requiresPermission: (p: string) => `Requires the '${p}' permission`,
}));

vi.mock("../api/queries", () => ({
  // Deliberately absent: `useServerProjectPipelines`. Rows read the pipeline
  // count off the project; if one reaches for a per-project request again this
  // mock throws and the suite says so.
  useCreateServerProject: () => ({ mutate: mocks.createProject, isPending: false }),
  useDeleteServerProject: () => ({ mutate: mocks.deleteProject, isPending: false }),
  useExecutionList: () => ({ data: { executions: mocks.runs }, isLoading: false }),
}));

vi.mock("../api/schedulesApi", () => ({
  useSchedules: () => ({ data: { schedules: mocks.schedules, count: mocks.schedules.length } }),
}));

vi.mock("../api/templatesApi", () => ({
  useTemplates: () => ({
    data: [{ type: "medallion_basic", name: "Medallion Basic", description: "Bronze, silver and gold, ready to run." }],
  }),
  useGenerateFromTemplate: () => ({ mutate: mocks.generateTemplate, isPending: false }),
}));

vi.mock("../api/mutations", () => ({
  apiErrorMessage: (_err: unknown, fallback: string) => fallback,
}));

const projects: ProjectSummary[] = [
  { id: "batch", name: "batch", pipelineCount: 6 },
  { id: "streaming", name: "streaming", pipelineCount: 3 },
];

function renderDashboard(list: ProjectSummary[] = projects) {
  return render(
    <MemoryRouter>
      <ProjectsList projects={list} />
    </MemoryRouter>
  );
}

beforeEach(() => {
  mocks.runs = [];
  mocks.schedules = [];
  mocks.deleteProject.mockReset();
  mocks.createProject.mockReset();
  mocks.generateTemplate.mockReset();
});

describe("Dashboard stat row", () => {
  it("shows running, failed-today and the next scheduled run as three numbers", () => {
    mocks.runs = [
      { id: "r-live", pipeline_name: "silver.clean", project_id: "batch", status: "running", started_at: hoursAgo(0.1) },
      { id: "r-fail", pipeline_name: "ml.student_performance", project_id: "batch", status: "failed", started_at: hoursAgo(1) },
    ];
    mocks.schedules = [
      { id: "s1", pipeline_name: "bronze.ingestion", enabled: true, next_run_at: inHours(3) },
    ];
    renderDashboard();

    const stats = screen.getByLabelText("Workspace at a glance");
    expect(within(stats).getByText("Running")).toBeInTheDocument();
    expect(within(stats).getByText("1", { selector: '[data-tone="active"]' })).toBeInTheDocument();
    expect(within(stats).getByText("1", { selector: '[data-tone="danger"]' })).toBeInTheDocument();
    expect(within(stats).getByText("bronze.ingestion")).toBeInTheDocument();
    // No boxed tiles or panels — a stat row with a single hairline underneath.
    expect(document.querySelector(".dash-tile")).toBeNull();
    expect(document.querySelector(".dash-panel")).toBeNull();
  });

  it("points at the schedules page when nothing is scheduled", () => {
    renderDashboard();
    expect(screen.getByRole("link", { name: "none scheduled" })).toHaveAttribute("href", "/workspace/schedules");
  });
});

describe("Needs attention", () => {
  it("lists a failed pipeline as one plain row that links to its run", () => {
    mocks.runs = [
      { id: "r-fail", pipeline_name: "ml.student_performance", project_id: "batch", status: "failed", started_at: hoursAgo(1) },
    ];
    renderDashboard();

    const row = screen.getByRole("link", { name: /ml.student_performance/ });
    expect(row).toHaveAttribute("href", "/workspace/executions?run=r-fail");
    expect(row.textContent).toContain("failed");
  });

  it("says so in one quiet line when nothing needs a look, instead of showing nothing", () => {
    mocks.runs = [
      { id: "r-ok", pipeline_name: "events", project_id: "streaming", status: "success", started_at: hoursAgo(2) },
    ];
    renderDashboard();
    expect(document.querySelector(".dash-attention")).toBeNull();
    expect(screen.getByText(/nothing failed or running/i)).toBeInTheDocument();
  });

  it("shows a pipeline that is currently running too", () => {
    mocks.runs = [
      { id: "r-live", pipeline_name: "silver.clean", project_id: "batch", status: "running", started_at: hoursAgo(0.1) },
    ];
    renderDashboard();
    const row = screen.getByRole("link", { name: /silver.clean/ });
    expect(row.textContent).toContain("running");
  });
});

describe("Projects", () => {
  it("is one card per project — name, pipeline count, last run", () => {
    mocks.runs = [
      { id: "r-fail", pipeline_name: "ml.student_performance", project_id: "batch", status: "failed", started_at: hoursAgo(1) },
    ];
    renderDashboard();

    const cardLinks = screen.getAllByRole("link").filter((l) => l.className === "dash-project-card-link");
    const card = cardLinks.find((l) => l.textContent?.startsWith("batch"))!;
    expect(within(card).getByText("6 pipelines")).toBeInTheDocument();
    expect(card.closest(".dash-project-card")).toHaveAttribute("data-health", "failing");

    const quiet = cardLinks.find((l) => l.textContent?.startsWith("streaming"))!;
    expect(within(quiet).getByText("No runs yet")).toBeInTheDocument();
    expect(quiet.closest(".dash-project-card")).not.toHaveAttribute("data-health");

    // No search, no sort, no view toggle — one grid of cards, always.
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Table" })).toBeNull();
  });

  it("links each card to its project", () => {
    renderDashboard();
    expect(screen.getByRole("link", { name: /streaming/ })).toHaveAttribute("href", "/p/streaming");
  });

  it("deletes from a quiet icon button on the card, no menu", () => {
    renderDashboard();
    expect(screen.queryByRole("button", { name: "Project options" })).toBeNull();
    expect(screen.getByRole("button", { name: "Delete streaming" })).toBeInTheDocument();
  });

  it("offers a way in when there are no projects", () => {
    renderDashboard([]);
    expect(screen.getByText("No projects yet")).toBeInTheDocument();
  });
});

describe("Deleting a project", () => {
  it("requires the exact project name before deleting", () => {
    renderDashboard([{ id: "project-1", name: "Analytics" }]);

    fireEvent.click(screen.getByRole("button", { name: "Delete Analytics" }));

    const deleteButton = screen.getByRole("button", { name: "Delete project" });
    expect(deleteButton).toBeDisabled();

    const typingField = screen.getByLabelText(/type analytics to confirm/i);
    fireEvent.change(typingField, { target: { value: "analytics" } });
    expect(deleteButton).toBeDisabled();

    fireEvent.change(typingField, { target: { value: "Analytics" } });
    expect(deleteButton).toBeEnabled();

    fireEvent.click(deleteButton);
    expect(mocks.deleteProject).toHaveBeenCalledWith(
      { projectId: "project-1", force: true },
      expect.objectContaining({ onSuccess: expect.any(Function) })
    );
  });
});

describe("Creating a project", () => {
  const openForm = () => {
    renderDashboard();
    fireEvent.click(screen.getByRole("button", { name: "New project" }));
    return screen.getByRole("textbox", { name: "Project name" });
  };

  it("creates an empty project from one form that submits on Enter", () => {
    const input = openForm();
    fireEvent.change(input, { target: { value: "my_project" } });
    fireEvent.submit(input.closest("form")!);

    expect(mocks.createProject).toHaveBeenCalledWith(
      { name: "my_project" },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
  });

  it("refuses a name the API would reject, before sending it", () => {
    const input = openForm();
    fireEvent.change(input, { target: { value: "1-bad name" } });

    expect(screen.getByText(/Start with a letter/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create project" })).toBeDisabled();
    fireEvent.submit(input.closest("form")!);
    expect(mocks.createProject).not.toHaveBeenCalled();
  });

  it("creates from a template when that is the starting point", () => {
    const input = openForm();
    fireEvent.click(screen.getByRole("radio", { name: /template/i }));
    expect(screen.getByText("Bronze, silver and gold, ready to run.")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "sales" } });
    fireEvent.submit(input.closest("form")!);

    expect(mocks.generateTemplate).toHaveBeenCalledWith(
      { template: "medallion_basic", project_name: "sales" },
      expect.objectContaining({ onError: expect.any(Function) })
    );
    expect(mocks.createProject).not.toHaveBeenCalled();
  });

  it("shows the server's refusal inside the form", () => {
    mocks.createProject.mockImplementation((_vars, opts) => opts.onError(new Error("409")));
    const input = openForm();
    fireEvent.change(input, { target: { value: "batch" } });
    fireEvent.submit(input.closest("form")!);

    expect(screen.getByRole("alert")).toHaveTextContent("Choose a unique name");
  });
});
