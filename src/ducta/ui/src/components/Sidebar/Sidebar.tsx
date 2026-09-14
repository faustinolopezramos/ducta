import React from "react";
import { Link, useLocation } from "react-router-dom";
import {
  IconLayoutDashboard,
  IconHistory,
  IconGitBranch,
  IconBox,
  IconFlask,
  IconShieldCheck,
  IconDatabaseImport,
  IconCalendarEvent,
} from "@tabler/icons-react";
import { SourceSwitcher } from "./SourceSwitcher";

/**
 * Icon rail — the narrow (56px) primary navigation. Labels are hidden by
 * default and revealed as a hover flyout so the rail stays out of the way and
 * the pipeline canvas keeps the maximum possible width. Each destination
 * switches the active domain (pipelines, quality, ingestion, MLOps, git).
 */
export function Sidebar() {
  const location = useLocation();

  // Grouped so the "projects" domain reads as distinct from workspace tools;
  // `divideBefore` renders a hairline separator above the item.
  const menuItems = [
    { label: "Dashboard", icon: IconLayoutDashboard, path: "/projects" },
    { label: "History", icon: IconHistory, path: "/workspace/executions", divideBefore: true },
    { label: "Schedules", icon: IconCalendarEvent, path: "/workspace/schedules" },
    { label: "Quality", icon: IconShieldCheck, path: "/workspace/quality" },
    { label: "Ingestion", icon: IconDatabaseImport, path: "/workspace/ingestion" },
    { label: "MLOps", icon: IconFlask, path: "/workspace/mlops" },
    { label: "Git", icon: IconGitBranch, path: "/workspace/git" },
  ];

  return (
    <aside className="ducta-rail" aria-label="Primary navigation">
      <Link to="/projects" className="ducta-rail-logo" title="Ducta" aria-label="Ducta home">
        <IconBox size={24} stroke={1.6} color="var(--primary)" />
      </Link>

      <nav className="ducta-rail-nav">
        {menuItems.map((item) => {
          const isActive =
            location.pathname === item.path ||
            (item.path !== "/" && location.pathname.startsWith(item.path));
          return (
            <React.Fragment key={item.path}>
              {item.divideBefore && <span className="rail-divider" aria-hidden="true" />}
              <Link
                to={item.path}
                className={`rail-item ${isActive ? "active" : ""}`}
                aria-label={item.label}
                aria-current={isActive ? "page" : undefined}
              >
                <item.icon size={20} stroke={1.5} />
                <span className="rail-flyout">{item.label}</span>
              </Link>
            </React.Fragment>
          );
        })}
      </nav>

      <div className="ducta-rail-footer">
        <SourceSwitcher compact />
        <div className="rail-version" title="Ducta v0.1.7">v0.1.7</div>
      </div>
    </aside>
  );
}
