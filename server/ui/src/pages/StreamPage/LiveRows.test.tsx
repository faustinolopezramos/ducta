import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { StreamRows } from "../../api/queries/streamRows";
import { LiveRows } from "./LiveRows";

const data = (rows: Record<string, unknown>[], over: Partial<StreamRows> = {}): StreamRows => ({
  node: "clean",
  available: true,
  sink: "parquet data/dev/silver/events",
  format: "parquet",
  columns: [
    { name: "event_id", type: "string" },
    { name: "amount", type: "double" },
  ],
  rows,
  total_rows: 12480,
  newest_at: "2026-11-16T12:14:00Z",
  ...over,
});

function setup(props: Partial<Parameters<typeof LiveRows>[0]> = {}) {
  const onPausedChange = vi.fn();
  const onLimitChange = vi.fn();
  const all = {
    node: "clean",
    data: data([{ event_id: "e2", amount: 2 }, { event_id: "e1", amount: 1.5 }]),
    updatedAt: Date.parse("2026-11-16T12:14:02Z"),
    loading: false,
    live: true,
    paused: false,
    onPausedChange,
    limit: 50 as const,
    onLimitChange,
    ...props,
  };
  const view = render(<LiveRows {...all} />);
  return { ...view, onPausedChange, onLimitChange, all };
}

describe("LiveRows", () => {
  it("shows the node's sink, its columns with their types, and its rows newest first", () => {
    setup();
    expect(screen.getByRole("region", { name: "Live data of clean" })).toHaveTextContent("parquet data/dev/silver/events");
    expect(screen.getByRole("columnheader", { name: "event_id" })).toHaveAttribute("title", "event_id: string");
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("e2");
    expect(rows[1]).toHaveTextContent("e1");
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("says how much is in the sink and when it last wrote", () => {
    setup({ updatedAt: Date.parse("2026-11-16T12:17:00Z") });
    expect(screen.getByRole("region", { name: /Live data/ })).toHaveTextContent("12,480 rows in the sink · last write 3 min ago · newest first");
  });

  it("does not mark the first read as new, only what arrives after it", () => {
    const { rerender, all } = setup();
    expect(document.querySelectorAll("tr.is-new")).toHaveLength(0);
    rerender(<LiveRows {...all} data={data([{ event_id: "e3", amount: 3 }, { event_id: "e2", amount: 2 }, { event_id: "e1", amount: 1.5 }])} />);
    const fresh = Array.from(document.querySelectorAll("tr.is-new"));
    expect(fresh).toHaveLength(1);
    expect(fresh[0]).toHaveTextContent("e3");
  });

  it("pauses and resumes, and says it is paused", async () => {
    const { onPausedChange, rerender, all } = setup();
    await userEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(onPausedChange).toHaveBeenCalledWith(true);
    rerender(<LiveRows {...all} paused />);
    expect(screen.getByText("Paused")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume" })).toHaveAttribute("aria-pressed", "true");
  });

  it("offers no pause for a stopped stream, whose rows are read once", () => {
    setup({ live: false });
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.getByText("Stopped")).toBeInTheDocument();
  });

  it("changes how many rows it shows", async () => {
    const { onLimitChange } = setup();
    await userEvent.click(within(screen.getByRole("group", { name: "Rows shown" })).getByRole("button", { name: "100" }));
    expect(onLimitChange).toHaveBeenCalledWith(100);
  });

  it("says why a sink cannot be read instead of drawing an empty grid", () => {
    setup({ data: { node: "clean", available: false, reason: "A 'kafka' sink has no rows to show here", columns: [], rows: [] } });
    expect(screen.getByRole("status")).toHaveTextContent("A 'kafka' sink has no rows to show here");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says nothing has been written yet, and that it is being read before the first answer", () => {
    const { rerender, all } = setup({ data: data([]) });
    expect(screen.getByRole("status")).toHaveTextContent("Nothing written yet");
    rerender(<LiveRows {...all} data={undefined} loading />);
    expect(screen.getByRole("status")).toHaveTextContent("Reading what clean has written");
  });

  it("shows a missing value as a dash and aligns numbers", () => {
    setup({ data: data([{ event_id: null, amount: 5 }]) });
    expect(screen.getByText("—")).toHaveClass("is-none");
    expect(screen.getByText("5")).toHaveClass("is-num");
  });
});
