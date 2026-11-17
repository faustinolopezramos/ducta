import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MiddleTruncate, distinctiveTail, fitHead } from "./MiddleTruncate";

describe("distinctiveTail", () => {
  it("keeps the part that tells similar names apart", () => {
    expect(distinctiveTail("golden.transformation_student")).toBe("_student");
    expect(distinctiveTail("golden.transformation_education")).toBe("_education");
    expect(distinctiveTail("bronze.education.student")).toBe(".student");
  });

  it("falls back to the last characters without a short separated end", () => {
    expect(distinctiveTail("abcdefghijklmnopqrstuvwxyz")).toBe("stuvwxyz");
    expect(distinctiveTail("short")).toBe("");
  });
});

describe("MiddleTruncate", () => {
  it("renders the whole name, split so only the head can shrink", () => {
    const { container } = render(<MiddleTruncate text="golden.transformation_student" />);
    expect(container.textContent).toBe("golden.transformation_student");
    expect(container.querySelector(".middle-trunc__tail")!.textContent).toBe("_student");
    expect(container.querySelector(".middle-trunc")!.getAttribute("title")).toBe("golden.transformation_student");
  });
});

describe("fitHead", () => {
  // One unit per character: widths read as character counts.
  const measure = (s: string) => s.length;

  it("leaves a name that fits whole", () => {
    expect(fitHead("silver.clean_education", "_education", 30, measure)).toBeNull();
  });

  it("fills the room exactly, so no gap opens before the tail", () => {
    const head = fitHead("golden.transformation_student", "_student", 20, measure)!;
    expect(head + "_student").toHaveLength(20);
    expect(head).toBe("golden.tran…");
  });

  it("keeps the head's first segment when there is room for it", () => {
    expect(fitHead("silver.clean_education", "_education", 18, measure)).toBe("silver.…");
  });

  it("cuts into the first segment when even it does not fit, so the … stays in view", () => {
    // 820 px: "silver." + "…" + "_education" did not fit, the head was clipped
    // and the name read "silv_education".
    const head = fitHead("silver.clean_education", "_education", 14, measure)!;
    expect(head).toBe("sil…");
    expect(head + "_education").toHaveLength(14);
  });
});
