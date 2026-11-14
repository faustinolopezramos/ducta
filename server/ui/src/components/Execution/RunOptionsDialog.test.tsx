import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RunOptionsDialog } from "./RunOptionsDialog";

const open = (onRun = vi.fn()) => {
  render(<RunOptionsDialog pipeline="silver.clean" env="dev" nodes={["silver.a", "silver.b"]} initialNode="silver.b" onRun={onRun} onCancel={() => {}} />);
  return onRun;
};

describe("RunOptionsDialog", () => {
  it("runs a scope from a node with parameters and a breakpoint", () => {
    const onRun = open();
    fireEvent.change(screen.getByLabelText("What to run"), { target: { value: "from" } });
    fireEvent.change(screen.getByLabelText(/Parameters/), { target: { value: '{"k": 1}' } });
    fireEvent.change(screen.getByLabelText(/Pause after/), { target: { value: "silver.b" } });
    fireEvent.click(screen.getByRole("button", { name: "Run in dev" }));
    expect(onRun).toHaveBeenCalledWith(
      expect.objectContaining({ scope: "from", node: "silver.b", hyperparams: { k: 1 }, pauseAfter: "silver.b", dryRun: false }),
    );
  });

  it("will not run with parameters that are not JSON", () => {
    const onRun = open();
    fireEvent.change(screen.getByLabelText(/Parameters/), { target: { value: "{oops" } });
    expect(screen.getByRole("button", { name: "Run in dev" })).toBeDisabled();
    expect(onRun).not.toHaveBeenCalled();
  });
});
