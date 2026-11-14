import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProblemsPanel } from "./ProblemsPanel";

describe("ProblemsPanel", () => {
  it("says so when there is nothing wrong", () => {
    render(<ProblemsPanel problems={[]} />);
    expect(screen.getByRole("status")).toHaveTextContent(/No problems/);
  });

  it("shows where a problem is and offers its fix", () => {
    const onOpen = vi.fn();
    const onFix = vi.fn();
    const problem = {
      severity: "error" as const,
      message: "Unknown key 'descripton'",
      code: "unknown_key",
      source: "config",
      file: "pipelines/etl.yaml",
      line: 4,
      node: "etl.clean",
      fix: { label: "Replace 'descripton' with 'description'", replace: ["descripton", "description"] as [string, string] },
    };
    render(<ProblemsPanel problems={[problem]} onOpen={onOpen} onFix={onFix} />);
    expect(screen.getByText("pipelines/etl.yaml:4 · etl.clean")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Unknown key 'descripton'"));
    expect(onOpen).toHaveBeenCalledWith(problem);
    fireEvent.click(screen.getByRole("button", { name: /Replace 'descripton'/ }));
    expect(onFix).toHaveBeenCalledWith(problem);
  });
});
