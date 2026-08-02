import { useEffect, useMemo, useRef, useState } from "react";
import { IconSearch, IconSitemap, IconArrowRight } from "@tabler/icons-react";

export interface PaletteNode {
  id: string;
  name?: string;
  type?: string;
  module?: string;
}

interface CommandPaletteProps {
  nodes: PaletteNode[];
  /** Names of other pipelines in the project (navigation targets). */
  pipelines: string[];
  onSelectNode: (id: string) => void;
  onOpenPipeline: (name: string) => void;
  onClose: () => void;
}

type PaletteEntry =
  | { kind: "node"; id: string; label: string; hint?: string }
  | { kind: "pipeline"; id: string; label: string };

/** ⌘K finder: type, Enter, and the canvas centers and selects the result. */
export function CommandPalette({ nodes, pipelines, onSelectNode, onOpenPipeline, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const entries = useMemo<PaletteEntry[]>(() => {
    const needle = query.trim().toLowerCase();
    const matchedNodes = nodes
      .filter((n) => {
        if (!needle) return true;
        return (
          (n.name ?? n.id).toLowerCase().includes(needle) ||
          n.id.toLowerCase().includes(needle) ||
          (n.module ?? "").toLowerCase().includes(needle)
        );
      })
      .slice(0, 8)
      .map((n): PaletteEntry => ({ kind: "node", id: n.id, label: n.name ?? n.id, hint: n.module }));
    const matchedPipelines = pipelines
      .filter((p) => (needle ? p.toLowerCase().includes(needle) : false))
      .slice(0, 4)
      .map((p): PaletteEntry => ({ kind: "pipeline", id: p, label: p }));
    return [...matchedNodes, ...matchedPipelines];
  }, [query, nodes, pipelines]);

  useEffect(() => { setActiveIndex(0); }, [query]);

  useEffect(() => {
    listRef.current
      ?.querySelector(`[data-index="${activeIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const pick = (entry: PaletteEntry) => {
    if (entry.kind === "node") onSelectNode(entry.id);
    else onOpenPipeline(entry.id);
    onClose();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, entries.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const entry = entries[activeIndex];
      if (entry) pick(entry);
    }
  };

  return (
    <div className="cmdk-overlay" onClick={onClose}>
      <div
        className="cmdk"
        role="dialog"
        aria-label="Find nodes and pipelines"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="cmdk-input-row">
          <IconSearch size={15} stroke={1.75} className="cmdk-search-icon" />
          <input
            ref={inputRef}
            className="cmdk-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a node or pipeline…"
            spellCheck={false}
          />
          <kbd className="cmdk-kbd">esc</kbd>
        </div>
        <div className="cmdk-list" ref={listRef}>
          {entries.length === 0 ? (
            <div className="cmdk-empty">No matches for "{query}"</div>
          ) : (
            entries.map((entry, i) => (
              <button
                key={`${entry.kind}:${entry.id}`}
                data-index={i}
                className={`cmdk-item ${i === activeIndex ? "active" : ""}`}
                onMouseEnter={() => setActiveIndex(i)}
                onClick={() => pick(entry)}
              >
                {entry.kind === "pipeline" ? (
                  <IconSitemap size={14} stroke={1.5} className="cmdk-item-icon" />
                ) : (
                  <span className="cmdk-node-dot" data-type={(nodes.find((n) => n.id === entry.id)?.type) ?? ""} />
                )}
                <span className="cmdk-item-label">{entry.label}</span>
                {entry.kind === "node" && entry.hint && (
                  <span className="cmdk-item-hint">{entry.hint}</span>
                )}
                {entry.kind === "pipeline" && (
                  <span className="cmdk-item-hint cmdk-item-goto">
                    open pipeline <IconArrowRight size={11} />
                  </span>
                )}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
