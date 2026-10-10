import React from "react";
import { Link, useLocation } from "react-router-dom";
import {
  IconLayoutDashboard,
  IconGitBranch,
  IconBox,
  IconFlask,
  IconShieldCheck,
  IconCode,
  IconPlayerPlay,
  IconSettings,
  IconCertificate,
} from "@tabler/icons-react";
import { useUIStore } from "../../store/uiStore";
import { projectIdFromPath, routes } from "../../utils/routes";
import { useServerProjectPipelines, useServerProjects } from "../../api/queries";

interface RailItem {
  label: string;
  icon: typeof IconBox;
  path: string;
  /** Active for exactly this path. */
  exact?: boolean;
  /** Other paths (and what is under them) this item stands for. */
  also?: string[];
  divideBefore?: boolean;
}

/**
 * What the rail offers: Projects (drill-down entry for Pipelines & Nodes),
 * followed by project tools (Code, Runs, Quality...) and workspace tools.
 * One item per concept — Schedules live in Runs, Connections in Settings.
 */
export function railItems(projectId: string | null, opts: { hasModels?: boolean } = {}): RailItem[] {
  const projectItems: RailItem[] = projectId
    ? [
        { label: "Code", icon: IconCode, path: routes.code(projectId) },
        {
          label: "Runs",
          icon: IconPlayerPlay,
          path: routes.runs(projectId),
          also: [routes.section(projectId, "schedules"), "/workspace/executions", "/workspace/schedules"],
        },
        {
          label: "Quality",
          icon: IconShieldCheck,
          path: routes.section(projectId, "quality"),
          also: ["/workspace/quality"],
        },
        ...(opts.hasModels ? [{ label: "Models", icon: IconFlask, path: routes.section(projectId, "models"), also: ["/workspace/mlops"] }] : []),
        { label: "Certificates", icon: IconCertificate, path: "/workspace/certificates", also: ["/verify-certificate"] },
        { label: "Git", icon: IconGitBranch, path: "/workspace/git" },
        { label: "Settings", icon: IconSettings, path: routes.section(projectId, "settings"), divideBefore: true },
      ]
    : [
        { label: "Code", icon: IconCode, path: "/projects" },
        {
          label: "Runs",
          icon: IconPlayerPlay,
          path: "/workspace/executions",
          also: ["/workspace/schedules"],
        },
        { label: "Quality", icon: IconShieldCheck, path: "/workspace/quality" },
        ...(opts.hasModels ? [{ label: "Models", icon: IconFlask, path: "/workspace/mlops" }] : []),
        { label: "Certificates", icon: IconCertificate, path: "/workspace/certificates", also: ["/verify-certificate"] },
        { label: "Git", icon: IconGitBranch, path: "/workspace/git" },
        { label: "Settings", icon: IconSettings, path: "/projects", divideBefore: true },
      ];

  return [
    {
      label: "Projects",
      icon: IconLayoutDashboard,
      path: "/projects",
      also: projectId
        ? [
            routes.project(projectId),
            routes.pipelines(projectId),
            `/p/${encodeURIComponent(projectId)}/datasets`,
          ]
        : [],
    },
    ...projectItems,
  ];
}

/** Whether *pathname* is *item*'s page or under it. */
export function isRailItemActive(item: RailItem, pathname: string): boolean {
  if (item.exact) return pathname === item.path;
  return [item.path, ...(item.also ?? [])].some((p) => {
    // If an 'also' path is a project root like /p/batch, match exact so child sections (runs, code...) stay distinct
    if (/^\/p\/[^/]+$/.test(p)) return pathname === p;
    return pathname === p || pathname.startsWith(`${p}/`);
  });
}

/**
 * Icon rail — the narrow primary navigation. Inside a project it leads with
 * that project's sections (pipelines, code, runs…), so moving between them
 * never loses which project you are in; workspace-wide pages follow. From a
 * workspace page, the last project opened stays one click away.
 */
export function Sidebar() {
  const location = useLocation();
  const lastProjectId = useUIStore((s) => s.lastProjectId);
  const { data: serverProjects } = useServerProjects();
  const firstProjectId = serverProjects?.projects?.[0]?.id ?? null;
  const projectId = projectIdFromPath(location.pathname) ?? lastProjectId ?? firstProjectId;
  const { data: pipelines } = useServerProjectPipelines(projectId ?? "");
  const specs = Object.values((pipelines?.pipelines ?? {}) as Record<string, { type?: string } | undefined>);
  const onModels = Boolean(projectId) && location.pathname.startsWith(routes.section(projectId ?? "", "models"));
  const items = railItems(projectId, { hasModels: onModels || specs.some((p) => p?.type === "ml") });

  return (
    <aside className="ducta-rail" aria-label="Primary navigation">
      <Link to="/projects" className="ducta-rail-logo" title="Ducta" aria-label="Ducta home">
        <IconBox size={24} stroke={1.6} color="var(--primary)" />
      </Link>

      <nav className="ducta-rail-nav">
        {items.map((item) => {
          const isActive = isRailItemActive(item, location.pathname);
          return (
            <React.Fragment key={item.label}>
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

      {/* The workspace is switched from the header, where its name is. */}
      <div className="ducta-rail-footer">
        <div className="rail-version" title={`Ducta v${__APP_VERSION__}`}>v{__APP_VERSION__}</div>
      </div>
    </aside>
  );
}
