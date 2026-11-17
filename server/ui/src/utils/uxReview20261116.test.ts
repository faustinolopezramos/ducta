import { describe, expect, it } from "vitest";
import { routes } from "./routes";
import { lensTitle } from "./lineage";
import { normalizeStatus } from "../components/ui/StatusBadge";
import { STATUS_META, EXECUTION_STATUSES } from "../components/ui/statusMeta";
import { isStuckQueued, summarizeRuns } from "./dashboardStats";
import { shortOsVersion } from "../components/GitSetup/GitSetupWizard";
import { formatDate } from "./formatDate";

describe("runs started from the CLI", () => {
  it("open their certificate, not a server run page they do not have", () => {
    expect(routes.runOrCertificate("batch", { id: "abc", origin: "cli", certificate_run_id: "abc" })).toBe(
      "/workspace/certificates/batch/abc",
    );
    expect(routes.runOrCertificate("batch", { id: "e1", origin: "server" })).toBe("/p/batch/runs/e1");
  });
});

describe("interrupted runs", () => {
  it("are a status of their own, offered as a filter", () => {
    expect(STATUS_META.interrupted.label).toBe("Interrupted");
    expect(EXECUTION_STATUSES).toContain("interrupted");
    expect(normalizeStatus("interrupted")).toBe("cancelled");
  });

  it("are neither queued, stuck nor running on the dashboard", () => {
    const old = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
    const run = { id: "x", pipeline_name: "p", status: "interrupted", started_at: old };
    expect(isStuckQueued(run)).toBe(false);
    expect(summarizeRuns([run]).active).toHaveLength(0);
  });
});

describe("small copy fixes", () => {
  it("says which way a lens tag points", () => {
    expect(lensTitle("up", 1)).toBe("Upstream: 1 step before the one in focus");
    expect(lensTitle("down", 2)).toBe("Downstream: 2 steps after the one in focus");
  });

  it("shortens the kernel's version line", () => {
    expect(
      shortOsVersion("Darwin Kernel Version 27.2.0: Wed Oct 14 23:48:06 PDT 2026; root:xnu-13432.41.4~25/RELEASE_ARM64_T8142"),
    ).toBe("Darwin 27.2.0");
    expect(shortOsVersion("10.0.22631")).toBe("10.0.22631");
    expect(shortOsVersion("")).toBe("");
  });

  it("writes dates in the UI's language, whatever the browser's", () => {
    // es-419 printed "13 nov, 07:47 p.m." next to English labels.
    expect(formatDate("2026-11-13T19:47:00Z")).toMatch(/^Nov 13/);
  });
});
