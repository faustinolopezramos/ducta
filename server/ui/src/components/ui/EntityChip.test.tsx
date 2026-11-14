import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { EntityChip } from "./EntityChip";

describe("EntityChip", () => {
  it("links to the entity and describes it with its card", () => {
    render(
      <MemoryRouter>
        <EntityChip kind="dataset" name="silver.students" to="/p/x/datasets/silver.students" card={[["Format", "delta"], ["Owner", null]]} />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: /silver\.students/ });
    expect(link).toHaveAttribute("href", "/p/x/datasets/silver.students");
    expect(link).toHaveAccessibleDescription(/Format delta/);
    expect(screen.queryByText("Owner")).not.toBeInTheDocument();
  });
});
