import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { GitPage } from "./GitPage";

vi.mock("../api/queries", () => ({
  useGitStatus: () => ({ data: { staged: [], unstaged: [], untracked: [], available: false }, isLoading: false }),
  useGitLog: () => ({ data: { commits: [] }, isLoading: false }),
  useGitAvailable: () => false,
}));
vi.mock("../api/mutations", () => ({
  useGitStage: () => ({ mutate: vi.fn(), isPending: false }),
  useGitCommitChanges: () => ({ mutate: vi.fn(), isPending: false }),
  useGitPull: () => ({ mutate: vi.fn(), isPending: false }),
  useGitPush: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("../components/FileTree", () => ({ FileTree: () => null }));

describe("GitPage outside a repository", () => {
  it("says the workspace is not a repository instead of 'Working tree clean'", () => {
    render(<MemoryRouter><GitPage /></MemoryRouter>);
    expect(screen.getByText("This workspace is not a Git repository")).toBeInTheDocument();
    expect(screen.queryByText("Working tree clean")).not.toBeInTheDocument();
    expect(screen.queryByText("No commits yet")).not.toBeInTheDocument();
  });
});
