import { useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { IconFlask, IconBrain } from "@tabler/icons-react";
import { PageContainer } from "../../components/ui/PageContainer";
import { PageHeader } from "../../components/ui/PageHeader";
import { Panel } from "../../components/ui/Panel";
import { Field } from "../../components/ui/Field";
import { Tabs, TabPanel, type TabItem } from "../../components/ui/Tabs";
import { useEnvironments } from "../../api/queries";
import { useSourceStore } from "../../store/workspace";
import { useMlPipelineOptions } from "./shared";
import { ExperimentsTab } from "./ExperimentsTab";
import { ModelRegistryTab } from "./ModelRegistryTab";

type Tab = "experiments" | "models";

const TABS: ReadonlyArray<TabItem<Tab>> = [
  {
    id: "experiments",
    label: "Experiments",
    icon: IconFlask,
    hint: "Tracked runs, their parameters and metrics",
  },
  {
    id: "models",
    label: "Model Registry",
    icon: IconBrain,
    hint: "Registered models and their versions",
  },
];

export function MLOpsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("experiments");
  const [searchParams, setSearchParams] = useSearchParams();
  const { projectId: routeProject } = useParams<{ projectId?: string }>();
  const activeEnv = useSourceStore((st) => st.activeEnv) || "base";

  const { data: allPipelineOptions, isLoading: pipelinesLoading } = useMlPipelineOptions();
  // Under a project, only its ML pipelines; the first one is shown until
  // another is picked, so the page never opens on an empty "pick one" state.
  const pipelineOptions = useMemo(
    () => (allPipelineOptions ?? []).filter((p) => !routeProject || p.projectId === routeProject),
    [allPipelineOptions, routeProject],
  );
  const env = searchParams.get("env") ?? activeEnv;
  const pipeline = searchParams.get("pipeline") ?? pipelineOptions[0]?.pipelineName ?? "";
  const project =
    searchParams.get("project") ??
    pipelineOptions.find((p) => p.pipelineName === pipeline)?.projectId ??
    routeProject ??
    "";

  const { data: environmentsData } = useEnvironments(project || undefined);
  const environments: string[] = environmentsData?.environments ?? [];

  const handlePipelineChange = (value: string) => {
    const next = new URLSearchParams(searchParams);
    const opt = pipelineOptions.find((p) => p.pipelineName === value);
    if (value && opt) {
      next.set("pipeline", value);
      next.set("project", opt.projectId);
    } else {
      next.delete("pipeline");
      next.delete("project");
    }
    setSearchParams(next, { replace: true });
  };

  const handleEnvChange = (value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value && value !== activeEnv) next.set("env", value);
    else next.delete("env");
    setSearchParams(next, { replace: true });
  };

  return (
    <PageContainer>
      <PageHeader
        title="Models"
        description="Experiment tracking and model registry."
        tabs={<Tabs items={TABS} value={activeTab} onChange={setActiveTab} label="Models view" />}
      />

      <Panel>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Field label="Pipeline">
            <select
              className="input-field"
              style={{ minWidth: 260 }}
              value={pipeline}
              onChange={(e) => handlePipelineChange(e.target.value)}
              aria-label="MLOps pipeline"
            >
              <option value="">
                {pipelinesLoading ? "Loading pipelines…" : "Select a pipeline…"}
              </option>
              {!pipelinesLoading && pipelineOptions.length === 0 && (
                <option value="" disabled>
                  No ML pipelines found in this workspace
                </option>
              )}
              {pipelineOptions.map((p) => (
                <option key={`${p.projectId}/${p.pipelineName}`} value={p.pipelineName}>
                  {p.projectName} / {p.pipelineName}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Environment">
            <select
              className="input-field"
              style={{ minWidth: 160 }}
              value={env}
              onChange={(e) => handleEnvChange(e.target.value)}
              aria-label="MLOps environment"
            >
              {["base", ...environments.filter((e) => e !== "base")].map((e) => (
                <option key={e} value={e}>
                  {e}{e === activeEnv ? " (active)" : ""}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </Panel>

      <TabPanel id={activeTab}>
        {activeTab === "experiments" && (
          <ExperimentsTab env={env || undefined} pipeline={pipeline || undefined} project={project || undefined} />
        )}
        {activeTab === "models" && (
          <ModelRegistryTab env={env || undefined} pipeline={pipeline || undefined} project={project || undefined} />
        )}
      </TabPanel>
    </PageContainer>
  );
}
