import { Modal } from "../ui/Modal";
import { KeyHint } from "../ui/KeyHint";
import { useShortcutsModal } from "./shortcutsStore";

interface ShortcutGroup {
  category: string;
  items: {
    label: string;
    keys: string;
    description?: string;
  }[];
}

const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    category: "General & Navigation",
    items: [
      { label: "Command Menu & Search", keys: "mod+k", description: "Open global omnibar to find pipelines, datasets, files, or actions" },
      { label: "Keyboard Shortcuts", keys: "?", description: "Display this cheat sheet" },
      { label: "Close active dialog or drawer", keys: "esc", description: "Dismiss current overlay or sheet" },
    ],
  },
  {
    category: "Workbench & Panels",
    items: [
      { label: "Toggle Explorer", keys: "mod+b", description: "Show or hide the workspace and dataset file tree" },
      { label: "Toggle Bottom Dock", keys: "mod+j", description: "Show or hide the execution logs and problems panel" },
      { label: "Zen Mode (Fullscreen)", keys: "alt+z", description: "Collapse all panels for maximum canvas focus" },
      { label: "Jump Node ↔ Code", keys: "mod+shift+g", description: "Navigate between selected DAG node and its Python definition" },
    ],
  },
  {
    category: "DAG Canvas",
    items: [
      { label: "Cycle Nodes", keys: "Tab", description: "Select next node (Shift+Tab for previous)" },
      { label: "Center Node / Fit Graph", keys: "Space", description: "Focus viewport on selected node or fit view" },
      { label: "Run Selected Node", keys: "r", description: "Trigger individual node execution" },
      { label: "Find on Canvas", keys: "/", description: "Filter nodes by name, status, layer or problem" },
    ],
  },
  {
    category: "Tabs & Controls",
    items: [
      { label: "Next / Previous Tab", keys: "ArrowRight", description: "Navigate active tablist with arrow keys" },
      { label: "First / Last Tab", keys: "Home", description: "Jump to first or last tab" },
    ],
  },
];

export function KeyboardShortcutsModal() {
  const { open, hide } = useShortcutsModal();

  if (!open) return null;

  return (
    <Modal open={open} onClose={hide} title="Keyboard Shortcuts" width={580}>
      <div style={{ display: "flex", flexDirection: "column", gap: 20, padding: "8px 0" }}>
        {SHORTCUT_GROUPS.map((group) => (
          <div key={group.category}>
            <div
              style={{
                fontSize: "var(--text-xs)",
                fontWeight: 600,
                color: "var(--text-muted)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                marginBottom: 8,
              }}
            >
              {group.category}
            </div>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                padding: "8px 12px",
              }}
            >
              {group.items.map((item) => (
                <div
                  key={item.label}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "4px 0",
                    gap: 12,
                  }}
                >
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    <span style={{ fontSize: "var(--text-sm)", color: "var(--text)", fontWeight: 500 }}>
                      {item.label}
                    </span>
                    {item.description && (
                      <span style={{ fontSize: "var(--text-2xs)", color: "var(--text-dim)" }}>
                        {item.description}
                      </span>
                    )}
                  </div>
                  <KeyHint keys={item.keys} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}
