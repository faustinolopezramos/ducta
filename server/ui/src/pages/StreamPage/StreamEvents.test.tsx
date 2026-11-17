import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StreamEvents } from "./StreamEvents";

describe("StreamEvents", () => {
  it("draws nothing when nothing happened", () => {
    const { container } = render(<StreamEvents events={[]} count={5} updatedAt={Date.now()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists what happened in words, the latest first, with a time counted back from the last poll", () => {
    const now = new Date(2026, 10, 16, 12, 14, 0).getTime();
    render(
      <StreamEvents
        events={[
          { at: 4, node: "enrich", kind: "failed" },
          { at: 8, node: "enrich", kind: "recovered" },
        ]}
        count={12}
        updatedAt={now}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("enrich recovered");
    expect(items[1]).toHaveTextContent("enrich failed");
    // 12 polls seen (0..11): event 8 is 3 polls (15 s) before the last, event 4 is 7 polls (35 s) before.
    expect(items[0]).toHaveTextContent("12:13");
    expect(items[1]).toHaveTextContent("12:13");
  });
});
