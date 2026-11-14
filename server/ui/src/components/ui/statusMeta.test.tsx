import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge, statusTone } from "./StatusBadge";
import { EXECUTION_STATUSES, FAILURE_STATUSES, STATUS_META } from "./statusMeta";

describe("status single source of truth", () => {
  it("covers every status the backend can send", () => {
    for (const status of EXECUTION_STATUSES) expect(STATUS_META[status]).toBeDefined();
  });

  it("labels gate_blocked as itself, not as the pill style it folds into", () => {
    render(<StatusBadge status="gate_blocked" />);
    expect(screen.getByText("Gate blocked")).toBeInTheDocument();
  });

  it("gives gate_blocked one tone everywhere and counts it as needing a look", () => {
    expect(statusTone("gate_blocked")).toBe(STATUS_META.gate_blocked.tone);
    expect(FAILURE_STATUSES.has("gate_blocked")).toBe(true);
  });

  it("folds aliases through the badge normalisation", () => {
    expect(statusTone("completed")).toBe("ok");
    expect(statusTone("nonsense")).toBe("neutral");
  });
});
