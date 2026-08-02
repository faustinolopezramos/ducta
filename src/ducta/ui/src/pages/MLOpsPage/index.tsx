import React, { useState } from "react";
import { colors } from "../../theme/tokens";
import { PageHeader } from "../../components/ui/PageHeader";
import { IconFlask, IconBrain } from "@tabler/icons-react";
import { ExperimentsTab } from "./ExperimentsTab";
import { ModelRegistryTab } from "./ModelRegistryTab";

type Tab = "experiments" | "models";

export function MLOpsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("experiments");

  const tabStyle = (tab: Tab): React.CSSProperties => ({
    padding: "8px 16px",
    fontSize: 13,
    fontWeight: activeTab === tab ? 600 : 400,
    color: activeTab === tab ? colors.accent : colors.textMuted,
    background: "none",
    border: "none",
    borderBottom: `2px solid ${activeTab === tab ? colors.accent : "transparent"}`,
    cursor: "pointer",
    transition: "color 0.15s, border-color 0.15s",
  });

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ padding: "24px 24px 0" }}>
        <PageHeader title="MLOps" description="Experiment tracking and model registry" />
      </div>

      <div
        style={{
          borderBottom: `1px solid ${colors.border}`,
          display: "flex",
          padding: "0 24px",
        }}
      >
        <button style={tabStyle("experiments")} onClick={() => setActiveTab("experiments")}>
          <IconFlask size={14} style={{ marginRight: 6, verticalAlign: "middle" }} />
          Experiments
        </button>
        <button style={tabStyle("models")} onClick={() => setActiveTab("models")}>
          <IconBrain size={14} style={{ marginRight: 6, verticalAlign: "middle" }} />
          Model Registry
        </button>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: 24 }}>
        {activeTab === "experiments" && <ExperimentsTab />}
        {activeTab === "models" && <ModelRegistryTab />}
      </div>
    </div>
  );
}
