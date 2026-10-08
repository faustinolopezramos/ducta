import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PermittedButton } from "./PermittedButton";

const allowed = vi.hoisted(() => ({ value: true }));

vi.mock("../../hooks/usePermission", () => ({
  usePermission: () => allowed.value,
  requiresPermission: (p: string) => `Requires the '${p}' permission`,
}));

describe("PermittedButton", () => {
  it("acts normally when the user has the permission", () => {
    allowed.value = true;
    const onClick = vi.fn();
    render(<PermittedButton permission="pipeline.execute" onClick={onClick} title="Run it">Run</PermittedButton>);
    const button = screen.getByRole("button", { name: "Run" });
    expect(button).toBeEnabled();
    expect(button).toHaveAttribute("title", "Run it");
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("stays visible but disabled, saying which permission it needs, when the user lacks it", () => {
    allowed.value = false;
    const onClick = vi.fn();
    render(<PermittedButton permission="pipeline.execute" onClick={onClick}>Run</PermittedButton>);
    const button = screen.getByRole("button", { name: "Run" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Requires the 'pipeline.execute' permission");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("keeps its own disabled state when the user has the permission", () => {
    allowed.value = true;
    render(<PermittedButton permission="pipeline.execute" disabled>Run</PermittedButton>);
    expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();
  });
});
