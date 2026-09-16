import { beforeAll, describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { DagCanvas } from "./DagCanvas";
import { buildStrata } from "../../utils/strata";
import type { DagCanvasItem } from "./types";

/** React Flow's documented jsdom setup — see DagCanvas.test.tsx for why each piece is needed. */
beforeAll(() => {
  class ResizeObserverMock {
    constructor(private readonly cb: ResizeObserverCallback) {}
    observe(target: Element) {
      const isNode = target.classList?.contains("react-flow__node");
      const contentRect = isNode ? { width: 200, height: 96 } : { width: 1200, height: 800 };
      this.cb([{ target, contentRect } as unknown as ResizeObserverEntry], this as unknown as ResizeObserver);
    }
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;

  if (!globalThis.DOMMatrixReadOnly) {
    class DOMMatrixReadOnlyMock {
      m22 = 1;
      constructor(readonly transform?: string) {}
    }
    // @ts-expect-error - minimal stand-in, only `m22` is read by React Flow.
    globalThis.DOMMatrixReadOnly = DOMMatrixReadOnlyMock;
  }

  Object.defineProperties(globalThis.HTMLElement.prototype, {
    offsetHeight: {
      configurable: true,
      get() {
        if (this.classList?.contains("react-flow__node")) return 96;
        return parseFloat(this.style.height) || 800;
      },
    },
    offsetWidth: {
      configurable: true,
      get() {
        if (this.classList?.contains("react-flow__node")) return 200;
        return parseFloat(this.style.width) || 1200;
      },
    },
  });
  (globalThis.SVGElement as unknown as { prototype: Record<string, unknown> }).prototype.getBBox = () => ({
    x: 0,
    y: 0,
    width: 0,
    height: 0,
  });
  globalThis.Element.prototype.getBoundingClientRect = function (this: Element) {
    const isHandle = this.classList?.contains("react-flow__handle");
    const isNode = this.classList?.contains("react-flow__node");
    const box = isHandle ? { width: 1, height: 1 } : isNode ? { width: 200, height: 96 } : { width: 1200, height: 800 };
    return { x: 0, y: 0, top: 0, left: 0, right: box.width, bottom: box.height, ...box, toJSON() { return this; } } as DOMRect;
  };
});

// A three-pipeline chain, one node each, wired by datasets.
const items: DagCanvasItem[] = [
  {
    id: "bronze.ingest_student",
    name: "bronze.ingest_student",
    pipeline: "bronze.ingestion",
    dependsOn: [],
    inputs: [],
    outputs: [{ id: "a-out", name: "bronze.education.student" }],
  },
  {
    id: "silver.clean_student",
    name: "silver.clean_student",
    pipeline: "silver.clean",
    dependsOn: [],
    inputs: [{ id: "b-in", name: "bronze.education.student" }],
    outputs: [{ id: "b-out", name: "silver.education.student_cleaned" }],
  },
  {
    id: "golden.transformation_student",
    name: "golden.transformation_student",
    pipeline: "golden.transformation",
    dependsOn: [],
    inputs: [{ id: "c-in", name: "silver.education.student_cleaned" }],
    outputs: [{ id: "c-out", name: "golden.education.student_summary" }],
  },
];

const order = ["bronze.ingestion", "silver.clean", "golden.transformation"];
const strata = buildStrata(items, order, "golden.transformation");

const bands = (container: HTMLElement) =>
  [...container.querySelectorAll<HTMLElement>('[data-testid="strata-band"]')];

describe("DagCanvas strata and orientation", () => {
  it("draws one labelled band per pipeline of the chain", () => {
    const { container } = render(<DagCanvas items={items} strata={strata} />);
    const drawn = bands(container);
    expect(drawn).toHaveLength(3);
    expect(drawn.map((b) => b.querySelector(".strata-band-pipe")!.textContent)).toEqual(order);
    expect(drawn.map((b) => b.getAttribute("data-layer"))).toEqual(["bronze", "silver", "gold"]);
  });

  it("marks the page's own pipeline and draws the rest as context", () => {
    const { container } = render(<DagCanvas items={items} strata={strata} />);
    expect(bands(container).filter((b) => b.classList.contains("current"))).toHaveLength(1);

    const context = [...container.querySelectorAll(".node-card--context")].map(
      (el) => el.querySelector(".node-card-name")!.textContent
    );
    expect(context.sort()).toEqual(["bronze.ingest_student", "silver.clean_student"]);
  });

  it("leaves the layer swatch to the band", () => {
    const { container } = render(<DagCanvas items={items} strata={strata} />);
    expect(container.querySelector(".node-card-swatch")).toBeNull();
  });

  it("draws no bands without a chain", () => {
    const { container } = render(<DagCanvas items={items} />);
    expect(bands(container)).toHaveLength(0);
  });

  it("puts ports on the top and bottom edges by default", () => {
    const { container } = render(<DagCanvas items={items} />);
    expect(container.querySelector(".react-flow__handle-top")).not.toBeNull();
    expect(container.querySelector(".react-flow__handle-left")).toBeNull();
    expect(container.querySelector(".node-card")!.getAttribute("data-orientation")).toBe("vertical");
  });

  it("moves ports to the sides and bands into columns when layers run left to right", () => {
    const { container } = render(<DagCanvas items={items} strata={strata} orientation="horizontal" />);
    expect(container.querySelector(".react-flow__handle-left")).not.toBeNull();
    expect(container.querySelector(".react-flow__handle-right")).not.toBeNull();
    expect(container.querySelector(".react-flow__handle-top")).toBeNull();
    expect(container.querySelector(".node-card")!.getAttribute("data-orientation")).toBe("horizontal");
    expect(bands(container).every((b) => b.getAttribute("data-orientation") === "horizontal")).toBe(true);
  });
});
