import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
  const seeded = useRef(false);

  // Seed the environment filter from the workspace's active environment on a
  // completely fresh visit — never seed `pipeline`/`project`, there is no
  // "current pipeline" to default to and the user must pick one explicitly.
  useEffect(() => {
    if (seeded.current) return;
    seeded.current = true;
    if (!searchParams.has("env") && !searchParams.has("pipeline") && !searchParams.has("project")) {
      const activeEnv = useSourceStore.getState().activeEnv;
      if (activeEnv) {
        const next = new URLSearchParams(searchParams);
        next.set("env", activeEnv);
        setSearchParams(next, { replace: true });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const env = searchParams.get("env") ?? "";
  const pipeline = searchParams.get("pipeline") ?? "";
  const project = searchParams.get("project") ?? "";

  const { data: pipelineOptions, isLoading: pipelinesLoading } = useMlPipelineOptions();
  const { data: environmentsData } = useEnvironments(project || undefined);
  const environments: string[] = environmentsData?.environments ?? [];

  const handlePipelineChange = (value: string) => {
    const next = new URLSearchParams(searchParams);
    const opt = (pipelineOptions ?? []).find((p) => p.pipelineName === value);
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
    if (value) next.set("env", value);
    else next.delete("env");
    setSearchParams(next, { replace: true });
  };

  return (
    <PageContainer>
      <PageHeader
        title="MLOps"
        description="Experiment tracking and model registry."
        backTo="/projects"
        backLabel="Dashboard"
        tabs={<Tabs items={TABS} value={activeTab} onChange={setActiveTab} label="MLOps view" />}
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
              {!pipelinesLoading && (pipelineOptions ?? []).length === 0 && (
                <option value="" disabled>
                  No ML pipelines found in this workspace
                </option>
              )}
              {(pipelineOptions ?? []).map((p) => (
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
              <option value="">(default)</option>
              {environments.map((e) => (
                <option key={e} value={e}>
                  {e}
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
