import React from "react";
import { Sidebar } from "../Sidebar/Sidebar";
import { Header } from "./Header";
import { Breadcrumbs } from "./Breadcrumbs";
import { StatusBar } from "../Shell/StatusBar";
import { envKind } from "../Shell/envKind";
import { useSourceStore } from "../../store/workspace";
import { useUIStore } from "../../store/uiStore";
import { useGlobalShortcuts } from "../Shell/useGlobalShortcuts";
import { ChangesPanel } from "../Git/ChangesPanel";
import { CommandMenu } from "../Shell/CommandMenu";

interface MainLayoutProps {
  children: React.ReactNode;
}

/**
 * The shell: rail, header (with the environment), the page, and a status
 * bar. `data-env-kind` frames the whole window when the environment is
 * production, so a run there is never mistaken for one in dev.
 */
export function MainLayout({ children }: MainLayoutProps) {
  const activeEnv = useSourceStore((s) => s.activeEnv);
  const density = useUIStore((s) => s.density);
  const kind = envKind(activeEnv);
  useGlobalShortcuts();
  return (
    <div className="ducta-app-layout" data-env-kind={kind} data-density={density}>
      <Sidebar />
      <div className="ducta-main-container">
        <Header />
        <Breadcrumbs />
        <main className="ducta-content">
          {children}
        </main>
        <StatusBar />
      </div>
      <ChangesPanel />
      <CommandMenu />
      {kind === "prod" && (
        <div className="ducta-env-frame" aria-hidden="true">
          <span className="ducta-env-frame__chip">PROD · {activeEnv}</span>
        </div>
      )}
    </div>
  );
}
