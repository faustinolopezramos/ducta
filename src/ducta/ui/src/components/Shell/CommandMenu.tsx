import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  IconBolt,
  IconCode,
  IconDatabase,
  IconFolder,
  IconHexagon,
  IconPlayerPlay,
  IconSearch,
  IconSitemap,
} from "@tabler/icons-react";
import {
  useCodeIndex,
  useExecutionList,
  useProjectDatasets,
  useServerProjectPipelines,
  useServerProjects,
} from "../../api/queries";
import { useUIStore } from "../../store/uiStore";
import { useLogsStore } from "../../store/logsStore";
import { useChangesPanel } from "../Git/changesStore";
import { projectIdFromPath, routes, type ProjectSection } from "../../utils/routes";
import { KeyHint } from "../ui/KeyHint";
import { buildCommandIndex, searchCommands, type CommandEntry, type CommandKind } from "./commandIndex";
import { useCommandMenu } from "./commandStore";

const ICON: Record<CommandKind, typeof IconBolt> = {
  command: IconBolt,
  project: IconFolder,
  pipeline: IconSitemap,
  node: IconHexagon,
  dataset: IconDatabase,
  file: IconCode,
  run: IconPlayerPlay,
};

const SECTIONS: [ProjectSection, string][] = [
  ["pipelines", "Pipelines"],
  ["runs", "Runs"],
  ["quality", "Quality"],
  ["models", "Models"],
  ["schedules", "Schedules"],
  ["connections", "Connections"],
  ["code", "Code"],
  ["settings", "Settings"],
];

/**
 * ⌘K anywhere: go to any pipeline, node, dataset, file or recent run of the
 * project — or run a command — by typing a few letters of it. `>` narrows to
 * commands, `#` to datasets, `@` to nodes.
 */
export function CommandMenu() {
  const { open, query: initial, kinds, hide } = useCommandMenu();
  if (!open) return null;
  return <Menu initial={initial} kinds={kinds} onClose={hide} />;
}

function Menu({ initial, kinds, onClose }: { initial: string; kinds: CommandKind[] | null; onClose: () => void }) {
  const navigate = useNavigate();
  const projectId = projectIdFromPath(useLocation().pathname) ?? "";
  const [query, setQuery] = useState(initial);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const { data: projects } = useServerProjects();
  const { data: pipelines } = useServerProjectPipelines(projectId);
  const { data: index } = useCodeIndex(projectId);
  const { data: datasets } = useProjectDatasets(projectId);
  const { data: runs } = useExecutionList({ project_id: projectId || undefined, limit: 15 });
  const toggleExplorer = useUIStore((s) => s.toggleExplorer);
  const density = useUIStore((s) => s.density);
  const setDensity = useUIStore((s) => s.setDensity);

  const entries = useMemo(() => {
    const commands: CommandEntry[] = [
      ...(projectId
        ? SECTIONS.map(([section, label]): CommandEntry => ({
            kind: "command",
            id: `go:${section}`,
            label: `Go to ${label}`,
            to: routes.section(projectId, section),
          }))
        : []),
      { kind: "command", id: "cmd:explorer", label: "Toggle explorer", hint: "mod+b", run: toggleExplorer },
      {
        kind: "command",
        id: "cmd:logs",
        label: "Toggle logs panel",
        hint: "mod+j",
        run: () => useLogsStore.getState().setLogsOpen(!useLogsStore.getState().logsOpen),
      },
      { kind: "command", id: "cmd:changes", label: "Review changes and commit", run: () => useChangesPanel.getState().setOpen(true) },
      {
        kind: "command",
        id: "cmd:density",
        label: density === "compact" ? "Use comfortable density" : "Use compact density",
        run: () => setDensity(density === "compact" ? "comfortable" : "compact"),
      },
    ];
    return buildCommandIndex({
      projectId,
      commands,
      projects: (projects?.projects ?? []).map((p: any) => ({ id: p.id ?? p.name, name: p.name })),
      pipelines: Object.keys(pipelines?.pipelines ?? {}),
      nodes: index?.nodes ?? [],
      datasets: datasets?.datasets ?? [],
      files: Object.keys(index?.files ?? {}),
      runs: runs?.executions ?? [],
    });
  }, [projectId, projects, pipelines, index, datasets, runs, toggleExplorer, density, setDensity]);

  const hits = useMemo(
    () => searchCommands(kinds ? entries.filter((e) => kinds.includes(e.kind)) : entries, query),
    [entries, query, kinds],
  );
  const [lastQuery, setLastQuery] = useState(query);
  if (query !== lastQuery) {
    setLastQuery(query);
    setActive(0);
  }

  useEffect(() => inputRef.current?.focus(), []);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [active]);

  const pick = (e: CommandEntry) => {
    onClose();
    if (e.run) e.run();
    else if (e.to) navigate(e.to);
  };

  return (
    <div className="cmdk-overlay" role="presentation" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="cmdk" role="dialog" aria-label="Go to anything">
        <div className="cmdk-input-row">
          <IconSearch size={15} stroke={1.75} className="cmdk-search-icon" />
          <input
            ref={inputRef}
            className="cmdk-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              kinds ? `Switch ${kinds.join(" / ")}…` : projectId ? "Pipelines, nodes, datasets, files, runs…  (> commands)" : "Projects…  (> commands)"
            }
            spellCheck={false}
            role="combobox"
            aria-expanded="true"
            aria-controls="command-menu-list"
            aria-activedescendant={hits[active] ? `cmd-${active}` : undefined}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                onClose();
              } else if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((i) => Math.min(i + 1, hits.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((i) => Math.max(i - 1, 0));
              } else if (e.key === "Enter" && hits[active]) {
                e.preventDefault();
                pick(hits[active]);
              }
            }}
          />
          <KeyHint keys="esc" className="cmdk-kbd" />
        </div>
        <div className="cmdk-list" ref={listRef} id="command-menu-list" role="listbox" aria-label="Results">
          {hits.length === 0 ? (
            <div className="cmdk-empty">No matches for “{query}”</div>
          ) : (
            hits.map((e, i) => {
              const Icon = ICON[e.kind];
              return (
                <button
                  key={e.id}
                  id={`cmd-${i}`}
                  type="button"
                  role="option"
                  aria-selected={i === active}
                  data-index={i}
                  className={`cmdk-item ${i === active ? "active" : ""}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => pick(e)}
                >
                  <Icon size={14} stroke={1.6} className="cmdk-item-icon" aria-hidden="true" />
                  <span className="cmdk-item-label">{e.label}</span>
                  {e.kind === "command" && e.hint?.includes("+") ? (
                    <KeyHint keys={e.hint} className="cmdk-item-hint" />
                  ) : (
                    e.hint && <span className="cmdk-item-hint">{e.hint}</span>
                  )}
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
