import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectWorkspaceForm } from "./ConnectWorkspaceForm";

const mocks = vi.hoisted(() => ({
  mutate: vi.fn(),
  updateSource: vi.fn(),
  navigate: vi.fn(),
  getRecentSources: vi.fn(() => [] as string[]),
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mocks.navigate };
});

vi.mock("../../hooks/useWorkspaceSelection", () => ({
  useWorkspaceSelection: () => ({
    selectedSource: null,
    isLoading: false,
    updateSource: mocks.updateSource,
  }),
}));

vi.mock("../../utils/storage", () => ({
  StorageService: { getRecentSources: () => mocks.getRecentSources() },
}));

let mutationState: { isPending: boolean; isError: boolean; error: unknown } = {
  isPending: false,
  isError: false,
  error: null,
};

vi.mock("../../api/mutations", () => ({
  useSelectSource: () => ({ ...mutationState, mutate: mocks.mutate }),
  apiErrorMessage: (_err: unknown, fallback: string) => fallback,
}));

function renderForm() {
  return render(
    <MemoryRouter>
      <ConnectWorkspaceForm />
    </MemoryRouter>,
  );
}

describe("ConnectWorkspaceForm", () => {
  beforeEach(() => {
    mocks.mutate.mockReset();
    mocks.updateSource.mockReset();
    mocks.navigate.mockReset();
    mocks.getRecentSources.mockReturnValue([]);
    mutationState = { isPending: false, isError: false, error: null };
  });

  it("disables Connect until something is typed", () => {
    renderForm();
    expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
  });

  it("submits the typed path, then connects on success", () => {
    renderForm();

    fireEvent.change(screen.getByLabelText("Folder path or Git URL"), {
      target: { value: "/tmp/my-project" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(mocks.mutate).toHaveBeenCalledWith(
      { path_or_url: "/tmp/my-project" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );

    // Simulate TanStack Query invoking the mutation's onSuccess callback.
    const [, { onSuccess }] = mocks.mutate.mock.calls[0];
    onSuccess({ source: { path: "/tmp/my-project" } });

    expect(mocks.updateSource).toHaveBeenCalledWith("/tmp/my-project");
    expect(mocks.navigate).toHaveBeenCalledWith("/projects", { replace: true });
  });

  it("shows a visible error message when the mutation fails", () => {
    mutationState = { isPending: false, isError: true, error: new Error("boom") };
    renderForm();

    expect(screen.getByRole("alert")).toHaveTextContent("Could not connect to that workspace.");
  });

  it("connects directly from a recent source without typing anything", () => {
    mocks.getRecentSources.mockReturnValue(["/tmp/recent-project"]);
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: /recent-project/ }));

    expect(mocks.mutate).toHaveBeenCalledWith(
      { path_or_url: "/tmp/recent-project" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("does not render a Recent section when there is no history", () => {
    renderForm();
    expect(screen.queryByText("Recent")).not.toBeInTheDocument();
  });
});
