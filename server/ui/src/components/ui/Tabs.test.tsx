import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IconFlask, IconBrain } from "@tabler/icons-react";
import { Tabs, TabPanel, type TabItem } from "./Tabs";

/**
 * The app's one tab strip. Every module that needed tabs had grown its own —
 * MLOps from an inline `tabStyle()`, the workspace connect form by hand, the
 * pipeline HUD a third way — and none implemented the arrow-key navigation the
 * `tab` role promises. These pin the WAI-ARIA behaviour down.
 */
type Id = "experiments" | "models" | "runs";

const ITEMS: ReadonlyArray<TabItem<Id>> = [
  { id: "experiments", label: "Experiments", icon: IconFlask },
  { id: "models", label: "Model Registry", icon: IconBrain, count: 4 },
  { id: "runs", label: "Runs" },
];

function setup(value: Id = "experiments") {
  const onChange = vi.fn();
  render(<Tabs items={ITEMS} value={value} onChange={onChange} label="MLOps view" />);
  return { onChange };
}

describe("Tabs", () => {
  it("exposes a labelled tablist", () => {
    setup();
    expect(screen.getByRole("tablist", { name: "MLOps view" })).toBeInTheDocument();
  });

  it("marks exactly one tab selected", () => {
    setup("models");
    const selected = screen.getAllByRole("tab").filter((t) => t.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0]).toHaveTextContent("Model Registry");
  });

  it("reports the selection on click", async () => {
    const { onChange } = setup();
    await userEvent.click(screen.getByRole("tab", { name: /Model Registry/ }));
    expect(onChange).toHaveBeenCalledWith("models");
  });

  it("shows a count only when one is given", () => {
    setup();
    expect(screen.getByRole("tab", { name: /Model Registry/ })).toHaveTextContent("4");
    expect(screen.getByRole("tab", { name: /^Runs$/ }).querySelector(".tabs-count")).toBeNull();
  });

  describe("keyboard", () => {
    it("puts only the selected tab in the tab order", () => {
      setup("models");
      const tabs = screen.getAllByRole("tab");
      expect(tabs.map((t) => t.getAttribute("tabindex"))).toEqual(["-1", "0", "-1"]);
    });

    it("moves to the next tab on ArrowRight", async () => {
      const { onChange } = setup("experiments");
      screen.getByRole("tab", { name: /Experiments/ }).focus();
      await userEvent.keyboard("{ArrowRight}");
      expect(onChange).toHaveBeenCalledWith("models");
    });

    it("moves to the previous tab on ArrowLeft", async () => {
      const { onChange } = setup("models");
      screen.getByRole("tab", { name: /Model Registry/ }).focus();
      await userEvent.keyboard("{ArrowLeft}");
      expect(onChange).toHaveBeenCalledWith("experiments");
    });

    it("wraps around at both ends", async () => {
      const first = setup("experiments");
      screen.getByRole("tab", { name: /Experiments/ }).focus();
      await userEvent.keyboard("{ArrowLeft}");
      expect(first.onChange).toHaveBeenCalledWith("runs");
    });

    it("jumps to the ends with Home and End", async () => {
      const { onChange } = setup("models");
      screen.getByRole("tab", { name: /Model Registry/ }).focus();
      await userEvent.keyboard("{Home}");
      expect(onChange).toHaveBeenCalledWith("experiments");
      await userEvent.keyboard("{End}");
      expect(onChange).toHaveBeenCalledWith("runs");
    });
  });
});

describe("TabPanel", () => {
  it("is wired to its tab both ways", () => {
    render(
      <>
        <Tabs items={ITEMS} value="models" onChange={() => {}} label="MLOps view" />
        <TabPanel id="models">registry</TabPanel>
      </>
    );
    const tab = screen.getByRole("tab", { name: /Model Registry/ });
    const panel = screen.getByRole("tabpanel");
    expect(tab).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveAttribute("aria-labelledby", tab.id);
  });
});
