import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { RunCertificate } from "../../api/certificatesApi";
import { CertificateOrigin } from "./CertificateSections";

const base = { run_id: "t1", pipeline: "train" } as unknown as RunCertificate;

const renderOrigin = (cert: RunCertificate) =>
  render(
    <MemoryRouter>
      <CertificateOrigin cert={cert} projectId="proj" />
    </MemoryRouter>
  );

describe("CertificateOrigin", () => {
  it("names the run whose failed checks started this retrain", () => {
    renderOrigin({
      ...base,
      triggered_by: { run_id: "score-run-1234", pipeline: "score", checks: ["prediction_drift"] },
    });
    const origin = screen.getByLabelText("Run origin");
    expect(origin).toHaveTextContent("Retrain started by run score-ru of score, whose prediction_drift check failed.");
    expect(screen.getByRole("link")).toHaveAttribute("href", "/workspace/certificates/proj/score-run-1234");
  });

  it("names the run a reproduction re-ran", () => {
    renderOrigin({ ...base, reproduction_of: "orig-run-5678" });
    expect(screen.getByLabelText("Run origin")).toHaveTextContent("Reproduction of run orig-run.");
  });

  it("says nothing about a run a person started", () => {
    const { container } = renderOrigin(base);
    expect(container).toBeEmptyDOMElement();
  });
});
