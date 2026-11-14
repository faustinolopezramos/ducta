import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SegmentedControl } from "./SegmentedControl";

describe("SegmentedControl", () => {
  it("marks the current option pressed and reports a new choice", () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl
        aria-label="View"
        value="map"
        onChange={onChange}
        options={[
          { value: "map", label: "Map" },
          { value: "list", label: "List", count: 3 },
        ]}
      />
    );
    expect(screen.getByRole("group", { name: "View" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Map" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "List 3" }));
    expect(onChange).toHaveBeenCalledWith("list");
  });
});
