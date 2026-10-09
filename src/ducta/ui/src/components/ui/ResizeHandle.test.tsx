import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResizeHandle } from "./ResizeHandle";

describe("ResizeHandle", () => {
  it("is a keyboard-operable window splitter", () => {
    const onChange = vi.fn();
    render(<ResizeHandle orientation="vertical" value={300} min={200} max={600} onChange={onChange} label="Resize inspector" panelAfter />);
    const handle = screen.getByRole("separator", { name: "Resize inspector" });
    expect(handle).toHaveAttribute("aria-valuenow", "300");
    // The panel is to the right: ← grows it, → shrinks it.
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith(316);
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith(284);
    fireEvent.keyDown(handle, { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith(600);
  });

  it("never goes past its bounds", () => {
    const onChange = vi.fn();
    render(<ResizeHandle orientation="horizontal" value={205} min={200} max={600} onChange={onChange} label="Resize panel" panelAfter />);
    fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowDown" });
    expect(onChange).toHaveBeenLastCalledWith(200);
  });

  it("restores the default size on double-click", () => {
    const onChange = vi.fn();
    render(<ResizeHandle orientation="vertical" value={500} min={200} max={600} onChange={onChange} label="Resize" defaultValue={400} />);
    fireEvent.doubleClick(screen.getByRole("separator"));
    expect(onChange).toHaveBeenCalledWith(400);
  });
});
