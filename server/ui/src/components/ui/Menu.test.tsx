import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Menu } from "./Menu";

function renderMenu(onSelect = vi.fn()) {
  render(
    <Menu
      triggerLabel="Account"
      trigger="me"
      items={[
        { key: "a", label: "Here", current: true },
        { key: "b", label: "Sign out", onSelect },
      ]}
    />,
  );
  return onSelect;
}

describe("Menu", () => {
  it("opens on click and runs the chosen item", () => {
    const onSelect = renderMenu();
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes on Escape and gives focus back to its button", () => {
    renderMenu();
    const button = screen.getByRole("button", { name: "Account" });
    fireEvent.click(button);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it("moves between items with the arrow keys", () => {
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    const [here, signOut] = screen.getAllByRole("menuitem");
    expect(document.activeElement).toBe(here);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(signOut);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(here);
  });
});
