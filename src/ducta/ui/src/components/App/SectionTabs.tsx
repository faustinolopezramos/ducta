import { useNavigate } from "react-router-dom";
import { Tabs } from "../ui";
import { routes } from "../../utils/routes";

/**
 * Sections that share one rail item and one header, told apart by a tab:
 * Runs (history · schedules) and Settings (environments · alerts · connections).
 * Each tab keeps its own URL, so links and the back button still work.
 */

export type RunsTab = "history" | "schedules" | "reliability";

export function RunsTabs({ projectId, current }: { projectId: string; current: RunsTab }) {
  const navigate = useNavigate();
  return (
    <Tabs
      label="Runs"
      value={current}
      items={[
        { id: "history" as const, label: "History" },
        { id: "schedules" as const, label: "Schedules" },
        { id: "reliability" as const, label: "Reliability" },
      ]}
      onChange={(id) => {
        if (id === "history") navigate(routes.runs(projectId));
        else if (id === "schedules") navigate(routes.section(projectId, "schedules"));
        else navigate(routes.section(projectId, "reliability"));
      }}
    />
  );
}

export type SettingsTab = "environments" | "alerts" | "connections" | "ai";

export const SETTINGS_TABS: { id: SettingsTab; label: string }[] = [
  { id: "environments", label: "Environments" },
  { id: "connections", label: "Connections" },
  { id: "alerts", label: "Alerts" },
  { id: "ai", label: "AI" },
];

export function SettingsTabs({ projectId, current }: { projectId: string; current: SettingsTab }) {
  const navigate = useNavigate();
  return (
    <Tabs
      label="Settings"
      value={current}
      items={SETTINGS_TABS}
      onChange={(id) => navigate(routes.section(projectId, "settings", id))}
    />
  );
}

/** A page shown inside a section group: the group's title and tabs replace its own. */
export interface SectionHeader {
  title: string;
  description?: string;
  tabs?: React.ReactNode;
}
