import { describe, expect, it } from "vitest";
import { joinPath, languageFor } from "./paths";

describe("code page paths", () => {
  it("joins a project root and a file without empty segments", () => {
    expect(joinPath("", "src/silver.py")).toBe("src/silver.py");
    expect(joinPath("projects/batch", "src/silver.py")).toBe("projects/batch/src/silver.py");
    expect(joinPath("projects/batch/", "/src/silver.py")).toBe("projects/batch/src/silver.py");
  });

  it("picks the editor language from the extension", () => {
    expect(languageFor("src/silver.py")).toBe("python");
    expect(languageFor("pipelines/silver.clean.yaml")).toBe("yaml");
    expect(languageFor("README")).toBe("plaintext");
  });
});
