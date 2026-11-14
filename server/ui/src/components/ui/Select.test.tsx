import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Select } from "./Select";

describe("Select", () => {
  it("renders with options and handles change", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Select aria-label="Fruit" onChange={onChange} defaultValue="apple">
        <option value="apple">Apple</option>
        <option value="banana">Banana</option>
      </Select>
    );

    const select = screen.getByRole("combobox", { name: "Fruit" });
    expect(select).toBeInTheDocument();
    expect(select).toHaveValue("apple");

    await user.selectOptions(select, "banana");
    expect(onChange).toHaveBeenCalled();
  });

  it("renders with label and helperText", () => {
    render(
      <Select label="Role" helperText="Choose your workspace role">
        <option value="admin">Admin</option>
        <option value="viewer">Viewer</option>
      </Select>
    );

    expect(screen.getByText("Role")).toBeInTheDocument();
    expect(screen.getByText("Choose your workspace role")).toBeInTheDocument();
  });

  it("applies error styling and aria-invalid", () => {
    render(
      <Select label="Environment" error helperText="Invalid environment">
        <option value="dev">Dev</option>
      </Select>
    );

    const select = screen.getByRole("combobox");
    expect(select).toHaveAttribute("aria-invalid", "true");
    expect(select).toHaveClass("select-error");
  });

  it("applies size and mono classes", () => {
    render(
      <Select size="sm" mono aria-label="Format">
        <option value="json">JSON</option>
      </Select>
    );

    const select = screen.getByRole("combobox");
    expect(select).toHaveClass("select-field--sm");
    expect(select).toHaveClass("select-field--mono");
  });

  it("supports disabled state", () => {
    render(
      <Select disabled aria-label="Disabled Select">
        <option value="none">None</option>
      </Select>
    );

    expect(screen.getByRole("combobox")).toBeDisabled();
  });

  it("links helper text to the select even without a label", () => {
    render(
      <>
        <Select helperText="Pick one" aria-label="First">
          <option value="a">A</option>
        </Select>
        <Select helperText="Pick another" aria-label="Second">
          <option value="b">B</option>
        </Select>
      </>
    );

    const [first, second] = screen.getAllByRole("combobox");
    const firstHelper = first.getAttribute("aria-describedby");
    expect(firstHelper).not.toContain("undefined");
    expect(firstHelper).not.toEqual(second.getAttribute("aria-describedby"));
    expect(document.getElementById(firstHelper!)).toHaveTextContent("Pick one");
  });

  it("is full width by default and shrinks with fullWidth={false}", () => {
    const { container } = render(
      <>
        <Select aria-label="Wide">
          <option value="a">A</option>
        </Select>
        <Select aria-label="Narrow" fullWidth={false}>
          <option value="b">B</option>
        </Select>
      </>
    );

    const [wide, narrow] = container.querySelectorAll(".select-container");
    expect(wide).not.toHaveClass("select-container--auto");
    expect(narrow).toHaveClass("select-container--auto");
  });
});
