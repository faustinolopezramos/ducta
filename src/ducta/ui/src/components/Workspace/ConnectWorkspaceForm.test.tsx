import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

// Partial: the form now pulls in FolderPicker -> api/client -> store/auth,
// which reads STORAGE_KEYS at module scope. A bare replacement mock leaves it
// undefined and the whole suite fails to import.
vi.mock("../../utils/storage", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../utils/storage")>();
  return {
    ...actual,
    StorageService: { ...actual.StorageService, getRecentSources: () => mocks.getRecentSources() },
  };
});

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
  // The local-folder picker queries the server for the directories it can
  // reach, so the form now needs a QueryClient. `retry: false` keeps a failed
  // fetch from stalling the test.
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ConnectWorkspaceForm />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The URL field and the Connect button live in Git mode only. */
function switchToGit() {
  fireEvent.click(screen.getByRole("tab", { name: /Git repository/ }));
}

describe("ConnectWorkspaceForm", () => {
  beforeEach(() => {
    mocks.mutate.mockReset();
    mocks.updateSource.mockReset();
    mocks.navigate.mockReset();
    mocks.getRecentSources.mockReturnValue([]);
    mutationState = { isPending: false, isError: false, error: null };
  });

  it("opens on the local-folder picker, not a bare text field", () => {
    renderForm();
    // Regression guard for the original complaint: a local folder had no
    // affordance at all — you had to know and type the absolute path.
    expect(screen.getByRole("tab", { name: /Local folder/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByLabelText("Repository URL")).not.toBeInTheDocument();
  });

  it("disables Connect until a URL is typed", () => {
    renderForm();
    switchToGit();
    expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
  });

  it("submits the typed URL, then connects on success", () => {
    renderForm();
    switchToGit();

    fireEvent.change(screen.getByLabelText("Repository URL"), {
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
    switchToGit();

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
