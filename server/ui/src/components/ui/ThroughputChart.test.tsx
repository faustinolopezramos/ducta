import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RateSpark, ThroughputChart, niceCeiling, pickPoints } from "./ThroughputChart";

const history = (total: number[], events: { at: number; node: string; kind: "failed" | "stalled" }[] = []) => ({
  total,
  input: total.map((v) => v * 1.1),
  events,
  count: total.length,
});

describe("niceCeiling", () => {
  it("rounds up to a number an axis can say", () => {
    expect(niceCeiling(3292)).toBe(4000);
    expect(niceCeiling(3600)).toBe(4000);
    expect(niceCeiling(940)).toBe(1000);
    expect(niceCeiling(41)).toBe(50);
    expect(niceCeiling(0)).toBe(1);
  });
});

describe("pickPoints", () => {
  it("keeps every point that fits", () => {
    expect(pickPoints([1, 2, 3], 10)).toEqual([0, 1, 2]);
  });

  it("keeps the ends and each bucket's low and high, so a peak or a drop survives", () => {
    const series = Array.from({ length: 720 }, (_, i) => (i === 300 ? 9000 : i === 500 ? 0 : 100 + (i % 3)));
    const picked = pickPoints(series, 200);
    expect(picked.length).toBeLessThanOrEqual(202);
    expect(picked[0]).toBe(0);
    expect(picked[picked.length - 1]).toBe(719);
    expect(picked).toContain(300);
    expect(picked).toContain(500);
    expect([...picked].sort((a, b) => a - b)).toEqual(picked); // in order: the path never goes back
  });
});

describe("ThroughputChart", () => {
  it("marks events as dots, named for screen readers, when asked to", () => {
    const { container } = render(
      <ThroughputChart history={history([10, 20, 30, 40], [{ at: 2, node: "enrich", kind: "stalled" }])} minutes={1} label="Throughput" marks="dot" />,
    );
    const dot = container.querySelector(".throughput-chart__event-dot--stalled");
    expect(dot).not.toBeNull();
    expect(dot).toHaveTextContent("enrich stalled");
    expect(container.querySelector(".throughput-chart__event-label")).toBeNull();
  });

  it("says it is collecting until there are two polls", () => {
    render(<ThroughputChart history={history([10])} minutes={1} label="Throughput" />);
    expect(screen.getByRole("img", { name: "Throughput" })).toHaveTextContent("Collecting…");
  });

  it("draws the axes, the processed line and the input line", () => {
    const { container } = render(<ThroughputChart history={history([3000, 3200, 3100, 3300])} minutes={10} label="Throughput" />);
    expect(screen.getByRole("img", { name: "Throughput" })).toBeInTheDocument();
    const text = container.textContent ?? "";
    expect(text).toContain("4k"); // top of the axis
    expect(text).toContain("−10 min");
    expect(text).toContain("−5 min");
    expect(text).toContain("now");
    expect(container.querySelector(".throughput-chart__line")).not.toBeNull();
    expect(container.querySelector(".throughput-chart__input")).not.toBeNull();
  });

  it("leaves out the middle label on a short span", () => {
    const { container } = render(<ThroughputChart history={history([1, 2, 3])} minutes={1} label="t" />);
    expect(container.textContent).not.toContain("−0 min");
    expect(container.textContent).toContain("−1 min");
  });

  it("marks where a node failed, by name", () => {
    const { container } = render(
      <ThroughputChart history={history([3, 3, 3, 1, 1], [{ at: 3, node: "score_events", kind: "failed" }])} minutes={1} label="t" />,
    );
    expect(container.querySelector(".throughput-chart__event")).not.toBeNull();
    expect(container.textContent).toContain("score_events failed");
  });

  it("ignores a mark that has scrolled off", () => {
    const { container } = render(
      <ThroughputChart history={{ ...history([3, 3, 3]), count: 500, events: [{ at: 2, node: "old", kind: "failed" }] }} minutes={1} label="t" />,
    );
    expect(container.querySelector(".throughput-chart__event")).toBeNull();
  });
});

describe("RateSpark", () => {
  it("needs two polls to draw anything", () => {
    const { container } = render(<RateSpark points={[5]} label="x" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws a labelled line", () => {
    render(<RateSpark points={[1, 5, 3]} label="Processed rows per second, recent polls" />);
    expect(screen.getByRole("img", { name: /Processed rows per second/ })).toBeInTheDocument();
  });
});
