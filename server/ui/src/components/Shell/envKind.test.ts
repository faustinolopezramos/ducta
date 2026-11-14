import { describe, expect, it } from "vitest";
import { envKind } from "./envKind";

describe("envKind", () => {
  it("recognises production by name", () => {
    expect(envKind("prod")).toBe("prod");
    expect(envKind("Production")).toBe("prod");
  });
  it("treats sandbox and staging-like names as staging", () => {
    for (const env of ["staging", "sandbox", "qa", "uat"]) expect(envKind(env)).toBe("staging");
  });
  it("anything else is a development environment; none is base", () => {
    expect(envKind("dev")).toBe("dev");
    expect(envKind("feature-x")).toBe("dev");
    expect(envKind("base")).toBe("base");
    expect(envKind(undefined)).toBe("base");
  });
});
