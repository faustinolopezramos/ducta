import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { RunRetrain } from "../../types/execution";
import { RetrainFact } from "./index";

const renderFact = (retrain: RunRetrain) =>
  render(
    <MemoryRouter>
      <RetrainFact retrain={retrain} projectId="proj" />
    </MemoryRouter>
  );

describe("RetrainFact", () => {
  it("names the training run and links its certificate", () => {
    renderFact({ pipeline: "train", checks: ["prediction_drift"], run_id: "train-run-1", status: "success" });
    expect(screen.getByText(/prediction_drift/).closest("span")).toHaveTextContent(
      "train · prediction_drift → completed train-ru"
    );
    expect(screen.getByRole("link")).toHaveAttribute("href", "/workspace/certificates/proj/train-run-1");
  });

  it("says why no training ran", () => {
    renderFact({ pipeline: "train", checks: ["prediction_drift"], skipped: "cooldown 1d" });
    expect(screen.getByText(/skipped/)).toHaveTextContent("train · prediction_drift → skipped: cooldown 1d");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows a failed retrain as failed", () => {
    renderFact({ pipeline: "train", checks: ["prediction_drift"], run_id: null, status: "failed", error: "boom" });
    expect(screen.getByText(/failed: boom/)).toHaveClass("run-page__retrain-failed");
  });
});
