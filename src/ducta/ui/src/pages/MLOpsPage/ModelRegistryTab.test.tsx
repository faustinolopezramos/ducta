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
    experiment_run_id: "run-abcdef12",
    stage: "Production",
    metrics: { val_auc: 0.95 },
    features: ["tenure_months", "monthly_spend"],
    artifact_sha256: "sha256:9d858ef8a836eaeb7aa45e4ae36b10ac",
  },
  { version: 1, stage: "Archived", metrics: {}, features: null, artifact_sha256: null },
];

const promote = vi.fn();
let promotionCheck: unknown = undefined;
vi.mock("../../api/mlopsApi", () => ({
  useMlopsStatus: () => ({ data: status }),
  useMlopsModels: () => ({ data: currentModels, isLoading: false, isError: false, refetch: vi.fn() }),
  useMlopsModelVersions: (name: string) => ({ data: name ? versions : undefined, isLoading: false }),
  useMlopsRunTable: () => ({
    data: { columns: [], rows: [{ run_id: "run-abcdef12", pipeline: "train", status: "COMPLETED", certificate_id: "cert1", certificate_ok: true }] },
  }),
  useModelHistory: (name: string) => ({
    data: name
      ? [
          {
            timestamp: "2026-11-11T16:05:00+00:00",
            event: "PROMOTE_REFUSED",
            model: "churn-model",
            version: 3,
            user: "ci",
            reason: "No reason provided",
            details: { refusal: "val_auc 0.70 < 0.90" },
          },
          {
            timestamp: "2026-11-11T15:40:00+00:00",
            event: "PROMOTE",
            model: "churn-model",
            version: 2,
            user: "ana",
            reason: "first model",
            details: { new_stage: "Production", demoted_versions: [1] },
          },
        ]
      : undefined,
    isLoading: false,
  }),
  usePromotionCheck: (_n: string, version: number) => ({ data: version ? promotionCheck : undefined, isLoading: false }),
  usePromoteModel: () => ({ mutate: promote, isPending: false }),
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

import { MemoryRouter } from "react-router-dom";
import { ModelRegistryTab as Tab } from "./ModelRegistryTab";

const ModelRegistryTab = (props: React.ComponentProps<typeof Tab>) => (
  <MemoryRouter>
    <Tab {...props} />
  </MemoryRouter>
);

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

  describe("after a retrain the policy refused", () => {
    const refused: ModelInfo = {
      name: "churn-model",
      latest_version: 3,
      stage: "Staging",
      framework: "sklearn",
      production_version: 2,
      production_metrics: { val_auc: 0.9 },
      latest_refusal: { reason: "val_auc 0.70 < 0.90" },
      served_by: [{ pipeline: "score", node: "score", stage: "production", version: null, streaming: false }],
    };

    it("files the model under Production and says what is serving and what was refused", () => {
      currentModels = [refused];
      try {
        render(<ModelRegistryTab pipeline="score" />);
        expect(screen.getByRole("heading", { name: "Production (1)" })).toBeInTheDocument();
        expect(screen.queryByRole("heading", { name: /Staging/ })).toBeNull();
        expect(screen.getByText(/In production:/)).toHaveTextContent("In production: v2 · val_auc 0.9000");
        expect(screen.getByText(/refused by the promotion policy/)).toHaveTextContent("val_auc 0.70 < 0.90");
        expect(screen.getByRole("button", { name: /Promote v3/ })).toBeInTheDocument();
      } finally {
        currentModels = models;
      }
    });

    it("shows the policy's verdict before promoting and needs a reason to force", () => {
      currentModels = [refused];
      promotionCheck = {
        policy: { metric: "val_auc", compare_to: "current_production", min_delta: 0 },
        passes: false,
        reason: "val_auc 0.70 does not beat 0.90",
        production_version: 2,
        served_by: refused.served_by,
      };
      try {
        render(<ModelRegistryTab pipeline="score" />);
        fireEvent.click(screen.getByRole("button", { name: /Promote v3/ }));
        const check = screen.getByLabelText("Promotion policy");
        expect(check).toHaveTextContent("✗ val_auc 0.70 does not beat 0.90");
        expect(check).toHaveTextContent("score › score will score with v3 from its next run; v2 → Archived.");
        fireEvent.click(screen.getByLabelText("Force (bypass the promotion policy)"));
        const go = screen.getByRole("button", { name: "Promote" });
        expect(go).toBeDisabled();
        fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "hotfix" } });
        fireEvent.click(go);
        expect(promote).toHaveBeenCalledWith(
          expect.objectContaining({ version: 3, stage: "production", force: true, reason: "hotfix" }),
          expect.anything()
        );
      } finally {
        currentModels = models;
        promotionCheck = undefined;
      }
    });
  });

  it("does not offer to delete the version in Production", () => {
    render(<ModelRegistryTab pipeline="score" />);
    fireEvent.click(screen.getByRole("button", { name: "Expand versions" }));
    const v2 = screen.getByText("v2", { selector: "td, td *" }).closest("tr") as HTMLElement;
    expect(within(v2).getByRole("button", { name: /Delete/ })).toBeDisabled();
    const v1 = screen.getByText("v1", { selector: "td, td *" }).closest("tr") as HTMLElement;
    expect(within(v1).getByRole("button", { name: /Delete/ })).toBeEnabled();
  });

  it("links each version to the run that trained it, and shows the history", () => {
    render(<ModelRegistryTab pipeline="score" />);
    fireEvent.click(screen.getByRole("button", { name: "Expand versions" }));
    const v2 = screen.getByText("v2", { selector: "td, td *" }).closest("tr") as HTMLElement;
    expect(within(v2).getByText("run-abcd")).toBeInTheDocument();
    expect(within(v2).getByRole("link")).toHaveAttribute("href", expect.stringMatching(/\/workspace\/certificates\/.*cert1$/));
    const history = screen.getByText("History").closest("details") as HTMLDetailsElement;
    history.open = true;
    fireEvent(history, new Event("toggle"));
    const items = within(screen.getByLabelText("History of churn-model")).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("ci promotion refused v3 · val_auc 0.70 < 0.90");
    expect(items[1]).toHaveTextContent("ana promoted v2 · → Production · archived v1 — “first model”");
  });
});
