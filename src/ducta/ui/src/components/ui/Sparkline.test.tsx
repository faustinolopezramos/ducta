import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("draws one bar per run and marks failures", () => {
    render(<Sparkline label="etl runs" points={[{ seconds: 1, status: "success" }, { seconds: 2, status: "failed" }]} />);
    const svg = screen.getByRole("img", { name: "etl runs" });
    expect(svg.querySelectorAll("rect")).toHaveLength(2);
    expect(svg.querySelectorAll(".is-failed")).toHaveLength(1);
  });
  it("says there is nothing to draw", () => {
    render(<Sparkline label="x" points={[]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
