import { describe, expect, it } from "vitest";
import { suggestCommitMessage } from "./commitMessage";

const c = (path: string, status = "modified") => ({ path, status, staged: false });

describe("suggestCommitMessage", () => {
  it("names pipelines, the catalog and settings in the project's terms", () => {
    expect(suggestCommitMessage([c("pipelines/silver.clean.yaml")])).toBe("Update pipeline silver.clean");
    expect(suggestCommitMessage([c("ducta.yaml"), c("src/silver.py")])).toBe("Update project settings and src/silver.py");
    expect(suggestCommitMessage([c("catalog/silver.yaml")])).toBe("Update catalog silver");
  });

  it("says Add or Remove when every change is one", () => {
    expect(suggestCommitMessage([c("src/new.py", "untracked")])).toBe("Add src/new.py");
    expect(suggestCommitMessage([c("src/old.py", "deleted")])).toBe("Remove src/old.py");
  });

  it("summarises many files", () => {
    const many = ["a", "b", "c", "d", "e"].map((x) => c(`src/${x}.py`));
    expect(suggestCommitMessage(many)).toBe("Update src/a.py, src/b.py and 3 more");
    expect(suggestCommitMessage([])).toBe("");
  });
});
