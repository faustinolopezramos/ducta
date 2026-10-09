import { useMemo, useState } from "react";
import { IconChevronDown, IconChevronRight, IconDatabase, IconSearch, IconSitemap } from "@tabler/icons-react";
import { useProjectDatasets } from "../../api/queries";
import { groupDatasets, filterTree, type ExplorerPipeline } from "./explorerModel";
import "./Explorer.css";

/** Drag payload of a dataset from the explorer (dropped on the canvas: a node that reads it). */
export const DATASET_DRAG_TYPE = "application/x-ducta-dataset";
export const FUNCTION_DRAG_TYPE = "application/x-ducta-function";

interface PipelineExplorerProps {
  projectId: string;
  currentPipeline: string;
  /** name → its node names, as the project lists them. */
  pipelines: Record<string, { nodes?: string[] } | undefined>;
  selectedNodeId: string | null;
  selectedDataset: string | null;
  /** Node ids with a failed last run or a problem — marked in the tree. */
  flaggedNodes?: ReadonlySet<string>;
  onSelectNode: (id: string, pipeline: string) => void;
  onSelectDataset: (name: string) => void;
  /** `module:function` of the project's functions no node runs yet — drag one in to make a node. */
  functions?: string[];
}

/**
 * The project as a tree: pipelines and their nodes, then the catalog by
 * layer. One click selects — on this canvas when it is drawn here, on its own
 * pipeline otherwise — so any node or dataset is two keystrokes away
 * (type to filter, Enter).
 */
export function PipelineExplorer({
  projectId,
  currentPipeline,
  pipelines,
  selectedNodeId,
  selectedDataset,
  flaggedNodes,
  onSelectNode,
  onSelectDataset,
  functions = [],
}: PipelineExplorerProps) {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const { data: datasetsData } = useProjectDatasets(projectId);

  const tree: ExplorerPipeline[] = useMemo(
    () =>
      Object.entries(pipelines)
        .map(([name, spec]) => ({ name, nodes: [...(spec?.nodes ?? [])] }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    [pipelines],
  );
  const filtered = useMemo(() => filterTree(tree, query), [tree, query]);
  const layers = useMemo(
    () => groupDatasets(datasetsData?.datasets ?? [], query),
    [datasetsData, query],
  );

  const toggle = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  // While filtering, everything that matches is shown open.
  const isOpen = (key: string, byDefault: boolean) => (query ? true : collapsed.has(key) ? !byDefault : byDefault);

  return (
    <nav className="explorer" aria-label="Project explorer">
      <div className="explorer__search">
        <IconSearch size={13} aria-hidden="true" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter nodes, datasets…"
          aria-label="Filter the explorer"
        />
      </div>
      <div className="explorer__scroll">
        <h3 className="explorer__section">Pipelines</h3>
        <ul className="explorer__list" role="tree" aria-label="Pipelines">
          {filtered.map((p) => {
            const open = isOpen(`p:${p.name}`, p.name === currentPipeline);
            return (
              <li key={p.name} role="treeitem" aria-expanded={open} aria-selected={false}>
                <button
                  type="button"
                  className={`explorer__row explorer__row--pipeline${p.name === currentPipeline ? " is-current" : ""}`}
                  onClick={() => toggle(`p:${p.name}`)}
                >
                  {open ? <IconChevronDown size={12} aria-hidden="true" /> : <IconChevronRight size={12} aria-hidden="true" />}
                  <IconSitemap size={13} aria-hidden="true" />
                  <span className="explorer__name">{p.name}</span>
                  <span className="explorer__count">{p.nodes.length}</span>
                </button>
                {open && (
                  <ul role="group" className="explorer__list">
                    {p.nodes.map((n) => (
                      <li key={n} role="treeitem" aria-selected={selectedNodeId === n}>
                        <button
                          type="button"
                          className={`explorer__row explorer__row--leaf${selectedNodeId === n ? " is-selected" : ""}`}
                          onClick={() => onSelectNode(n, p.name)}
                          title={n}
                        >
                          <span className="explorer__node-glyph" aria-hidden="true">◇</span>
                          <span className="explorer__name">{n}</span>
                          {flaggedNodes?.has(n) && <span className="explorer__flag" aria-label="needs attention">●</span>}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
          {filtered.length === 0 && <li className="explorer__empty">No pipeline or node matches.</li>}
        </ul>

        <h3 className="explorer__section">Catalog</h3>
        <ul className="explorer__list" role="tree" aria-label="Datasets">
          {layers.map((layer) => {
            const open = isOpen(`l:${layer.layer}`, false);
            return (
              <li key={layer.layer} role="treeitem" aria-expanded={open} aria-selected={false}>
                <button type="button" className="explorer__row explorer__row--pipeline" data-layer={layer.layer} onClick={() => toggle(`l:${layer.layer}`)}>
                  {open ? <IconChevronDown size={12} aria-hidden="true" /> : <IconChevronRight size={12} aria-hidden="true" />}
                  <IconDatabase size={13} aria-hidden="true" />
                  <span className="explorer__name">{layer.layer}</span>
                  <span className="explorer__count">{layer.datasets.length}</span>
                </button>
                {open && (
                  <ul role="group" className="explorer__list">
                    {layer.datasets.map((d) => (
                      <li key={d} role="treeitem" aria-selected={selectedDataset === d}>
                        <button
                          type="button"
                          className={`explorer__row explorer__row--leaf${selectedDataset === d ? " is-selected" : ""}`}
                          onClick={() => onSelectDataset(d)}
                          title={`${d} — drag onto the canvas to add a node that reads it`}
                          draggable
                          onDragStart={(e) => {
                            e.dataTransfer.setData(DATASET_DRAG_TYPE, d);
                            e.dataTransfer.setData("text/plain", d);
                            e.dataTransfer.effectAllowed = "copy";
                          }}
                        >
                          <span className="explorer__name">{d}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
          {layers.length === 0 && <li className="explorer__empty">No dataset matches.</li>}
        </ul>

        {functions.length > 0 && (
          <>
            <h3 className="explorer__section">Functions without a node</h3>
            <ul className="explorer__list" aria-label="Functions without a node">
              {functions
                .filter((f) => !query || f.toLowerCase().includes(query.toLowerCase()))
                .map((f) => (
                  <li key={f}>
                    <span
                      className="explorer__row explorer__row--leaf explorer__row--drag"
                      title={`${f} — drag onto the canvas to make it a node`}
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData(FUNCTION_DRAG_TYPE, f);
                        e.dataTransfer.setData("text/plain", f);
                        e.dataTransfer.effectAllowed = "copy";
                      }}
                    >
                      <span className="explorer__node-glyph" aria-hidden="true">ƒ</span>
                      <span className="explorer__name">{f.split(":").pop()}</span>
                      <span className="explorer__count">{f.split(":")[0]}</span>
                    </span>
                  </li>
                ))}
            </ul>
          </>
        )}
      </div>
    </nav>
  );
}
