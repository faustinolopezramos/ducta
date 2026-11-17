import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StreamStartCheck } from "./StreamStartCheck";

const plan = {
  pipeline: "events_stream",
  env: "dev",
  ok: false,
  issues: [],
  nodes: [
    {
      name: "clean",
      source: "file_stream parquet data/bronze",
      sink: "parquet data/silver",
      trigger: "every 5 seconds",
      output_mode: "append",
      after: [],
      issues: [{ level: "error" as const, text: "transform 'clean_events' is not registered" }],
    },
  ],
};

describe("StreamStartCheck", () => {
  it("names the pipeline and environment and the problem, and starts nothing by itself", async () => {
    const onCheckAgain = vi.fn();
    const onClose = vi.fn();
    render(<StreamStartCheck plan={plan} pipeline="events_stream" env="dev" onCheckAgain={onCheckAgain} onClose={onClose} />);
    expect(screen.getByRole("dialog")).toHaveTextContent("events_stream can’t start in dev");
    expect(screen.getByText("transform 'clean_events' is not registered")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Start stream/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(onCheckAgain).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
