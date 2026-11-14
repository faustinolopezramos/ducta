import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InheritedValue } from "./InheritedValue";

describe("InheritedValue", () => {
  it("says where an inherited value comes from", () => {
    render(<InheritedValue value={120} source="pipeline defaults" />);
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("pipeline")).toBeInTheDocument();
  });
  it("marks an environment override and shows a node's own value plainly", () => {
    render(<InheritedValue value={5} source="node" overridden />);
    expect(screen.getByLabelText("overridden by this environment")).toBeInTheDocument();
    expect(screen.queryByText("node")).toBeNull();
  });
});
