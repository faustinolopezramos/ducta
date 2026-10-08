import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CertificateNode, CertificateNodeML } from "../../api/certificatesApi";
import { MLSection, describeSplit } from "./CertificateSections";

const SPLIT = { method: "stratified", test_size: 0.2, stratify_col: "churned", seed: 42 };

function node(name: string, ml?: Partial<CertificateNodeML>): CertificateNode {
  return {
    name,
    type: "batch",
    status: "success",
    duration_seconds: 1,
    outputs: [],
    ...(ml
      ? {
          ml: {
            stage: "training",
            split: SPLIT,
            split_source: "pipeline",
            split_required: true,
            split_applied: true,
            model_version: "1.0",
            hyperparams: { max_depth: 6 },
            ...ml,
          },
        }
      : {}),
  };
}

function row(name: string) {
  return screen.getByText(name).closest("tr") as HTMLElement;
}

describe("MLSection", () => {
  it("shows a node that applied its split as applied", () => {
    render(<MLSection nodes={[node("train", {})]} />);
    expect(within(row("train")).getByText("applied")).toBeInTheDocument();
    expect(within(row("train")).getByText("stratified, test_size=0.2, stratify_col=churned, seed=42")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("flags a bound node that did not apply its split, and says so above the table", () => {
    render(<MLSection nodes={[node("train", { split_applied: false })]} />);
    expect(within(row("train")).getByText("not applied")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("train was given a train/test split and did not apply it");
  });

  it("does not blame a feature node that was not bound to the split", () => {
    render(<MLSection nodes={[node("features", { stage: null, split_required: false, split_applied: false })]} />);
    expect(within(row("features")).getByText("not required")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("names the exact model a serving node scored with", () => {
    render(
      <MLSection
        nodes={[
          node("score", {
            stage: "serving",
            split: null,
            split_required: false,
            split_applied: false,
            model: {
              source: "ducta",
              name: "churn",
              version: 3,
              stage_at_resolution: "production",
              uri: "model_registry/artifacts/x/v3",
              framework: "sklearn",
              artifact_sha256: "sha256:abc",
              hash_source: "registry",
            },
          }),
        ]}
      />,
    );
    expect(within(row("score")).getByText("churn v3 (production)")).toBeInTheDocument();
  });

  it("is absent for a certificate with no ML evidence (older runs, batch pipelines)", () => {
    const { container } = render(<MLSection nodes={[node("load")]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("describeSplit", () => {
  it("puts the method first and leaves out empty values", () => {
    expect(describeSplit({ seed: 1, method: "random", test_size: 0.3, val_size: null })).toBe("random, test_size=0.3, seed=1");
  });

  it("shows a dash when there is no split", () => {
    expect(describeSplit(null)).toBe("—");
  });
});
