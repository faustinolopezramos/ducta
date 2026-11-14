import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { KeyboardShortcutsModal } from "./KeyboardShortcutsModal";
import { useShortcutsModal } from "./shortcutsStore";

describe("KeyboardShortcutsModal", () => {
  beforeEach(() => {
    useShortcutsModal.getState().hide();
  });

  it("is not rendered when closed", () => {
    render(<KeyboardShortcutsModal />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders when opened and displays shortcuts groups", () => {
    useShortcutsModal.getState().show();
    render(<KeyboardShortcutsModal />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Keyboard Shortcuts" })).toBeInTheDocument();
    expect(screen.getByText("General & Navigation")).toBeInTheDocument();
    expect(screen.getByText("Workbench & Panels")).toBeInTheDocument();
    expect(screen.getByText("Command Menu & Search")).toBeInTheDocument();
  });

  it("closes on close button or Escape key", () => {
    useShortcutsModal.getState().show();
    render(<KeyboardShortcutsModal />);

    const closeBtn = screen.getByLabelText("Close modal");
    fireEvent.click(closeBtn);
    expect(useShortcutsModal.getState().open).toBe(false);
  });
});
