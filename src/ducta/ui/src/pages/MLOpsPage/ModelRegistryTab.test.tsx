import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MlopsStatus, ModelInfo, ModelVersion } from "../../api/mlopsApi";

const models: ModelInfo[] = [
  {
    name: "churn-model",
    latest_version: 2,
    stage: "Production",
    framework: "sklearn",
    served_by: [
      { pipeline: "score", node: "score", stage: "production", version: null, streaming: false },
      { pipeline: "live", node: "score_events", stage: null, version: 1, streaming: true },
    ],
  },
];
let currentModels: ModelInfo[] = models;
const status: MlopsStatus = {
  storage_path: "/w/models",
  mlops_enabled: false,
  tracking_present: false,
  registry_present: false,
  unregistered_models: [
    { name: "risk_model", versions: 3, latest: "/w/models/risk_model/20261010/model.pkl", updated_at: "2026-10-10T02:50:32+00:00" },
  ],
};
const versions: ModelVersion[] = [
  {
    version: 2,
    stage: "Production",
    metrics: { val_auc: 0.95 },
    features: ["tenure_months", "monthly_spend"],
    artifact_sha256: "sha256:9d858ef8a836eaeb7aa45e4ae36b10ac",
  },
  { version: 1, stage: "Archived", metrics: {}, features: null, artifact_sha256: null },
];

vi.mock("../../api/mlopsApi", () => ({
  useMlopsStatus: () => ({ data: status }),
  useMlopsModels: () => ({ data: currentModels, isLoading: false, isError: false, refetch: vi.fn() }),
  useMlopsModelVersions: (name: string) => ({ data: name ? versions : undefined, isLoading: false }),
  usePromoteModel: () => ({ mutate: vi.fn(), isPending: false }),
  useRunMlopsGc: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteModelVersion: () => ({ mutateAsync: vi.fn() }),
}));
vi.mock("../../hooks/usePermission", () => ({
  usePermission: () => true,
  requiresPermission: (p: string) => `Requires the '${p}' permission`,
}));
vi.mock("../../components/ui/PermittedButton", () => ({
  PermittedButton: ({ children, onClick }: { children: React.ReactNode; onClick: () => void }) => (
    <button type="button" onClick={onClick}>
      {children}
    </button>
  ),
}));

import { ModelRegistryTab } from "./ModelRegistryTab";

describe("ModelRegistryTab", () => {
  it("says why it is empty and lists models saved without tracking", () => {
    currentModels = [];
    try {
      render(<ModelRegistryTab env="dev" pipeline="score" />);
      expect(screen.getByText("MLOps tracking is off in 'dev'")).toBeInTheDocument();
      expect(screen.getByText("risk_model")).toBeInTheDocument();
    } finally {
      currentModels = models;
    }
  });

  it("says which project nodes serve each model, and what they ask for", () => {
    render(<ModelRegistryTab pipeline="score" />);
    const served = screen.getByLabelText("Served by");
    expect(served).toHaveTextContent("score › score @ production");
    expect(served).toHaveTextContent("live › score_events v1 (stream)");
  });

  it("shows each version's real stage, metrics, features and artifact hash", () => {
    render(<ModelRegistryTab pipeline="score" />);
    fireEvent.click(screen.getByRole("button", { name: "Expand versions" }));
    const v2 = screen.getByText("v2", { selector: "td, td *" }).closest("tr") as HTMLElement;
    expect(within(v2).getByText("Production")).toBeInTheDocument();
    expect(within(v2).getByText("val_auc: 0.9500")).toBeInTheDocument();
    expect(within(v2).getByText("tenure_months, monthly_spend")).toBeInTheDocument();
    expect(within(v2).getByText("9d858ef8a836")).toBeInTheDocument();
    const v1 = screen.getByText("v1", { selector: "td, td *" }).closest("tr") as HTMLElement;
    expect(within(v1).getByText("Archived")).toBeInTheDocument();
  });
});
