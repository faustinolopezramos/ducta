import { useParams } from "react-router-dom";
import { PageContainer, PageHeader } from "../../components/ui";
import { SETTINGS_TABS, SettingsTabs, type SettingsTab } from "../../components/App/SectionTabs";
import IngestionPage from "../IngestionPage";
import { EnvironmentsDiff } from "./EnvironmentsDiff";
import { AlertRules } from "./AlertRules";

const DESCRIPTIONS: Record<SettingsTab, string> = {
  environments: "What each environment changes, side by side.",
  connections: "The databases your ingestion nodes read from.",
  alerts: "Who hears about failures, quality gates and missed SLAs.",
};

/** `/p/:projectId/settings[/:tab]` — the project's configuration, by topic. */
export function ProjectSettingsPage() {
  const { projectId = "", tab } = useParams<{ projectId: string; tab?: string }>();
  const current: SettingsTab = SETTINGS_TABS.some((t) => t.id === tab) ? (tab as SettingsTab) : "environments";
  const header = {
    title: "Settings",
    description: DESCRIPTIONS[current],
    tabs: <SettingsTabs projectId={projectId} current={current} />,
  };

  // Connections is a page of its own (with its actions); it takes this header.
  if (current === "connections") return <IngestionPage header={header} />;

  return (
    <PageContainer>
      <PageHeader title={header.title} description={header.description} tabs={header.tabs} />
      {current === "alerts" ? <AlertRules projectId={projectId} /> : <EnvironmentsDiff projectId={projectId} />}
    </PageContainer>
  );
}
