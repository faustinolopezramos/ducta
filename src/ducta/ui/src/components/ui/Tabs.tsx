import type React from "react";
import type { Icon } from "@tabler/icons-react";
import "./Tabs.css";

export interface TabItem<T extends string = string> {
  id: T;
  label: string;
  icon?: Icon;
  /** Count shown after the label — omit rather than pass 0 to hide the pill. */
  count?: number;
  /** Tooltip explaining what this view is for. */
  hint?: string;
}

interface TabsProps<T extends string> {
  items: ReadonlyArray<TabItem<T>>;
  value: T;
  onChange: (id: T) => void;
  /** Accessible name for the tablist. */
  label: string;
}

/**
 * The app's one tab strip.
 *
 * Every module that needed tabs had grown its own: MLOps built one from an
 * inline `tabStyle()` function, the workspace connect form hand-rolled another,
 * and the pipeline HUD has a third. Three looks, three keyboard behaviours, and
 * only one of them implemented the arrow-key navigation the tab role implies.
 *
 * Follows the WAI-ARIA tabs pattern: one stop in the tab order, arrows to move
 * between tabs, Home/End to jump to the ends.
 */
export function Tabs<T extends string>({ items, value, onChange, label }: TabsProps<T>) {
  const move = (delta: number) => {
    const index = items.findIndex((t) => t.id === value);
    if (index < 0) return;
    const next = items[(index + delta + items.length) % items.length];
    onChange(next.id);
    // Selection follows focus, so the newly selected tab has to take it too.
    document.getElementById(`tab-${next.id}`)?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    switch (e.key) {
      case "ArrowRight":
        e.preventDefault();
        move(1);
        break;
      case "ArrowLeft":
        e.preventDefault();
        move(-1);
        break;
      case "Home":
        e.preventDefault();
        onChange(items[0].id);
        document.getElementById(`tab-${items[0].id}`)?.focus();
        break;
      case "End":
        e.preventDefault();
        onChange(items[items.length - 1].id);
        document.getElementById(`tab-${items[items.length - 1].id}`)?.focus();
        break;
    }
  };

  return (
    // The key handler sits on each tab, not on the tablist: the tabs are what
    // hold focus, so that is where the event actually originates.
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map((tab) => {
        const active = tab.id === value;
        const Icon = tab.icon;
        return (
          <button
            key={tab.id}
            id={`tab-${tab.id}`}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={`tabpanel-${tab.id}`}
            // Only the selected tab is in the tab order; arrows move within.
            tabIndex={active ? 0 : -1}
            title={tab.hint}
            className={`tabs-tab${active ? " active" : ""}`}
            onClick={() => onChange(tab.id)}
            onKeyDown={onKeyDown}
          >
            {Icon && <Icon size={14} stroke={1.6} />}
            <span>{tab.label}</span>
            {tab.count != null && <span className="tabs-count">{tab.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** The region a tab controls. Pairs with `Tabs` for the aria wiring. */
export function TabPanel({
  id,
  children,
  className,
}: {
  id: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      id={`tabpanel-${id}`}
      role="tabpanel"
      aria-labelledby={`tab-${id}`}
      tabIndex={0}
      className={className}
    >
      {children}
    </div>
  );
}
