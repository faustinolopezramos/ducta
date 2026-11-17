import { describe, expect, it } from "vitest";
import { formatCell, rowKeys } from "./rowFormat";

describe("formatCell", () => {
  it("shows nothing as a dash, in its own kind", () => {
    expect(formatCell(null)).toEqual({ text: "—", kind: "none" });
    expect(formatCell(undefined)).toEqual({ text: "—", kind: "none" });
  });

  it("keeps integers whole and floats short, numbers aligned as numbers", () => {
    expect(formatCell(10231)).toEqual({ text: "10231", kind: "num" });
    expect(formatCell(42.1)).toEqual({ text: "42.1", kind: "num" });
    expect(formatCell(0.1 + 0.2)).toEqual({ text: "0.3", kind: "num" });
  });

  it("reads a timestamp to the second", () => {
    expect(formatCell("2026-11-16T12:14:02.123Z")).toEqual({ text: "2026-11-16 12:14:02", kind: "time" });
    expect(formatCell("2026-11-16T12:14:02")).toEqual({ text: "2026-11-16 12:14:02", kind: "time" });
    expect(formatCell("2026-11-16T12:14:02+01:00").text).toBe("2026-11-16 12:14:02");
  });

  it("leaves text, booleans and nested values", () => {
    expect(formatCell("books")).toEqual({ text: "books", kind: "text" });
    expect(formatCell(true)).toEqual({ text: "true", kind: "bool" });
    expect(formatCell({ a: 1 })).toEqual({ text: '{"a":1}', kind: "text" });
  });
});

describe("rowKeys", () => {
  it("gives the same key to the same row on the next poll, and a new one to a new row", () => {
    const before = rowKeys([{ id: 2 }, { id: 1 }]);
    const after = rowKeys([{ id: 3 }, { id: 2 }, { id: 1 }]);
    expect(after.slice(1)).toEqual(before);
    expect(after[0]).not.toBe(before[0]);
  });

  it("tells identical rows apart", () => {
    const keys = rowKeys([{ a: 1 }, { a: 1 }]);
    expect(new Set(keys).size).toBe(2);
  });
});
